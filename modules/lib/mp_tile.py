#!/usr/bin/env python3
'''
access satellite map tile database

some functions are based on code from mapUtils.py in gmapcatcher

Andrew Tridgell
May 2012
released under GNU GPL v3 or later
'''

import math, cv, sys, os, mp_util, httplib2, threading, time, collections, string, hashlib, errno

class TileException(Exception):
	'''tile error class'''
	def __init__(self, msg):
		Exception.__init__(self, msg)

TILE_SERVICES = {
	# thanks to http://go2log.com/2011/09/26/fetching-tiles-for-offline-map/
	# for the URL mapping info
	"GoogleSat"      : "http://khm${GOOG_DIGIT}.google.com/kh/v=113&src=app&x=${X}&y=${Y}&z=${ZOOM}&s=${GALILEO}",
	"GoogleMap"      : "http://mt${GOOG_DIGIT}.google.com/vt/lyrs=m@121&hl=en&x=${X}&y=${Y}&z=${ZOOM}&s=${GALILEO}",
	"GoogleHyb"      : "http://mt${GOOG_DIGIT}.google.com/vt/lyrs=h@121&hl=en&x=${X}&y=${Y}&z=${ZOOM}&s=${GALILEO}",
	"GoogleTer"      : "http://mt${GOOG_DIGIT}.google.com/vt/lyrs=t@108,r@121&hl=en&x=${X}&y=${Y}&z=${ZOOM}&s=${GALILEO}",
	"GoogleChina"    : "http://mt${GOOG_DIGIT}.google.cn/vt/lyrs=m@121&hl=en&gl=cn&x=${X}&y=${Y}&z=${ZOOM}&s=${GALILEO}",
	"YahooMap"       : "http://maps${Y_DIGIT}.yimg.com/hx/tl?v=4.3&.intl=en&x=${X}&y=${YAHOO_Y}&z=${YAHOO_ZOOM}&r=1",
	"YahooSat"       : "http://maps${Y_DIGIT}.yimg.com/ae/ximg?v=1.9&t=a&s=256&.intl=en&x=${X}&y=${YAHOO_Y}&z=${YAHOO_ZOOM}&r=1",
	"YahooInMap"     : "http://maps.yimg.com/hw/tile?locale=en&imgtype=png&yimgv=1.2&v=4.1&x=${X}&y=${YAHOO_Y}&z=${YAHOO_ZOOM_2}",
	"YahooInHyb"     : "http://maps.yimg.com/hw/tile?imgtype=png&yimgv=0.95&t=h&x=${X}&y=${YAHOO_Y}&z=${YAHOO_ZOOM_2}",
	"YahooHyb"       : "http://maps${Y_DIGIT}.yimg.com/hx/tl?v=4.3&t=h&.intl=en&x=${X}&y=${YAHOO_Y}&z=${YAHOO_ZOOM}&r=1",
	"MicrosoftBrMap" : "http://imakm${MS_DIGITBR}.maplink3.com.br/maps.ashx?v=${QUAD}|t&call=2.2.4",
	"MicrosoftHyb"   : "http://ecn.t${MS_DIGIT}.tiles.virtualearth.net/tiles/h${QUAD}.png?g=441&mkt=en-us&n=z",
	"MicrosoftSat"   : "http://ecn.t${MS_DIGIT}.tiles.virtualearth.net/tiles/a${QUAD}.png?g=441&mkt=en-us&n=z",
	"MicrosoftMap"   : "http://ecn.t${MS_DIGIT}.tiles.virtualearth.net/tiles/r${QUAD}.png?g=441&mkt=en-us&n=z",
	"MicrosoftTer"   : "http://ecn.t${MS_DIGIT}.tiles.virtualearth.net/tiles/r${QUAD}.png?g=441&mkt=en-us&shading=hill&n=z",
	"OpenStreetMap"  : "http://tile.openstreetmap.org/${ZOOM}/${X}/${Y}.png",
	"OSMARender"     : "http://tah.openstreetmap.org/Tiles/tile/${ZOOM}/${X}/${Y}.png",
	"OpenAerialMap"  : "http://tile.openaerialmap.org/tiles/?v=mgm&layer=openaerialmap-900913&x=${X}&y=${Y}&zoom=${OAM_ZOOM}",
	"OpenCycleMap"   : "http://andy.sandbox.cloudmade.com/tiles/cycle/${ZOOM}/${X}/${Y}.png"
	}

# these are the md5sums of "unavailable" tiles
BLANK_TILES = set(["d16657bbee25d7f15c583f5c5bf23f50",
                   "c0e76e6e90ff881da047c15dbea380c7",
		   "d41d8cd98f00b204e9800998ecf8427e"])

# all tiles are 256x256
TILES_WIDTH = 256
TILES_HEIGHT = 256

class TileServiceInfo:
	'''a lookup object for the URL templates'''
	def __init__(self, x, y, zoom):
		self.X = x
		self.Y = y
		self.Z = zoom
		quadcode = ''
		for i in range(zoom - 1, -1, -1):
			quadcode += str((((((y >> i) & 1) << 1) + ((x >> i) & 1))))
		self.ZOOM = zoom
		self.QUAD = quadcode
		self.YAHOO_Y = 2**(zoom-1) - 1 - y
		self.YAHOO_ZOOM = zoom + 1
		self.YAHOO_ZOOM_2 = 17 - zoom + 1
		self.OAM_ZOOM = 17 - zoom
		self.GOOG_DIGIT = (x + y) & 3
		self.MS_DIGITBR = (((y & 1) << 1) + (x & 1)) + 1
		self.MS_DIGIT = (((y & 3) << 1) + (x & 1))
		self.Y_DIGIT = (x + y + zoom) % 3 + 1
		self.GALILEO = "Galileo"[0:(3 * x + y) & 7]

	def __getitem__(self, a):
		return str(getattr(self, a))


class TileInfo:
	'''description of a tile'''
	def __init__(self, tile, zoom, offset=(0,0)):
		self.tile = tile
		(self.x, self.y) = tile
		self.zoom = zoom
		(self.offsetx, self.offsety) = offset
		self.refresh_time()

	def key(self):
		'''tile cache key'''
		return (self.tile, self.zoom)

	def refresh_time(self):
		'''reset the request time'''
		self.request_time = time.time()

	def coord(self, offset=(0,0)):
		'''return lat,lon within a tile given (offsetx,offsety)'''
		(tilex, tiley) = self.tile
		(offsetx, offsety) = offset
		world_tiles = 1<<self.zoom
		x = ( tilex + 1.0*offsetx/TILES_WIDTH ) / (world_tiles/2.) - 1
		y = ( tiley + 1.0*offsety/TILES_HEIGHT) / (world_tiles/2.) - 1
		lon = x * 180.0
		y = math.exp(-y*2*math.pi)
		e = (y-1)/(y+1)
		lat = 180.0/math.pi * math.asin(e)
		return (lat, lon)

	def size(self):
		'''return tile size as (width,height) in meters'''
		(lat1, lon1) = self.coord((0,0))
		(lat2, lon2) = self.coord((TILES_WIDTH,0))
		width = mp_util.gps_distance(lat1, lon1, lat2, lon2)
		(lat2, lon2) = self.coord((0,TILES_HEIGHT))
		height = mp_util.gps_distance(lat1, lon1, lat2, lon2)
		return (width,height)

	def distance(self, lat, lon):
		'''distance of this tile from a given lat/lon'''
		(tlat, tlon) = self.coord((TILES_WIDTH/2,TILES_HEIGHT/2))
		return mp_util.gps_distance(lat, lon, tlat, tlon)

	def path(self):
		'''return relative path of tile image'''
		(x, y) = self.tile
		return "%u/%u/%u.img" % (self.zoom, y, x)

	def url(self, service):
		'''return URL for a tile'''
		url = string.Template(TILE_SERVICES[service])
		(x,y) = self.tile
		tile_info = TileServiceInfo(x, y, self.zoom)
		return url.substitute(tile_info)
		

class TileInfoScaled(TileInfo):
	'''information on a tile with scale information and placement'''
	def __init__(self, tile, zoom, scale, src, dst):
		TileInfo.__init__(self, tile, zoom)
		self.scale = scale
		(self.srcx, self.srcy) = src
		(self.dstx, self.dsty) = dst

		

class MPTile:
	'''map tile object'''
	def __init__(self, cache_path=None, download=True, cache_size=500,
		     service="MicrosoftSat", tile_delay=0.3, debug=False,
		     max_zoom=19):
		if cache_path is None:
			cache_path = os.path.join(os.environ['HOME'], '.tilecache')
		self.cache_path = cache_path
		self.max_zoom = max_zoom
		self.min_zoom = 1
		self.download = download
		self.cache_size = cache_size
		self.tile_delay = tile_delay
		self.service = service
		self.debug = debug

		if service not in TILE_SERVICES:
			raise TileException('unknown tile service %s' % service)

		# _download_pending is a dictionary of TileInfo objects
		self._download_pending = {}
		self._download_thread = None
		self._loading = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'data', 'loading.jpg')
		self._unavailable = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'data', 'unavailable.jpg')
		self._tile_cache = collections.OrderedDict()

	def coord_to_tile(self, lat, lon, zoom):
		'''convert lat/lon/zoom to a TileInfo'''
		world_tiles = 1<<zoom
		x = world_tiles / 360.0 * (lon + 180.0)
		tiles_pre_radian = world_tiles / (2 * math.pi)
		e = math.sin(lat * (1/180.*math.pi))
		y = world_tiles/2 + 0.5*math.log((1+e)/(1-e)) * (-tiles_pre_radian)
		offsetx = int((x - int(x)) * TILES_WIDTH)
		offsety = int((y - int(y)) * TILES_HEIGHT)
		return TileInfo((int(x) % world_tiles, int(y) % world_tiles), zoom, offset=(offsetx, offsety))

	def tile_to_path(self, tile):
		'''return full path to a tile'''
		return os.path.join(self.cache_path, self.service, tile.path())

	def coord_to_tilepath(self, lat, lon, zoom):
		'''return the tile ID that covers a latitude/longitude at
		a specified zoom level
		'''
		tile = self.coord_to_tile(lat, lon, zoom)
		return self.tile_to_path(tile)

	def tiles_pending(self):
		'''return number of tiles pending download'''
		return len(self._download_pending)

	def downloader(self):
		'''the download thread'''
		http = httplib2.Http()
		while self.tiles_pending() > 0:
			time.sleep(self.tile_delay)

			keys = list(self._download_pending.keys())[:]

			# work out which one to download next, choosing by request_time
			tile_info = self._download_pending[keys[0]]
			for key in keys:
				if self._download_pending[key].request_time > tile_info.request_time:
					tile_info = self._download_pending[key]
			
			url = tile_info.url(self.service)
			path = self.tile_to_path(tile_info)
			key = tile_info.key()
			
			try:
				if self.debug:
					print(("Downloading %s [%u left]" % (url, len(keys))))
				resp,img = http.request(url)
			except httplib2.HttpLib2Error as e:
				#print('Error loading %s' % url)
				self._tile_cache[key] = self._unavailable
				self._download_pending.pop(key)
				if self.debug:
					print(("Failed %s: %s" % (url, str(e))))
				continue
			if 'content-type' not in resp or resp['content-type'].find('image') == -1:
				self._tile_cache[key] = self._unavailable
				self._download_pending.pop(key)
				if self.debug:
					print(("non-image response %s" % url))
				continue
				

			# see if its a blank/unavailable tile
			md5 = hashlib.md5(img).hexdigest()
			if md5 in BLANK_TILES:
				if self.debug:
					print(("blank tile %s" % url))
				self._tile_cache[key] = self._unavailable
				self._download_pending.pop(key)
				continue

			mp_util.mkdir_p(os.path.dirname(path))
			h = open(path+'.tmp','w')
			h.write(img)
			h.close()
			os.rename(path+'.tmp', path)
			self._download_pending.pop(key)
		self._download_thread = None

	def start_download_thread(self):
		'''start the downloader'''
		if self._download_thread:
			return
		t = threading.Thread(target=self.downloader)
		t.daemon = True
		self._download_thread = t
		t.start()

	def load_tile_lowres(self, tile):
		'''load a lower resolution tile from cache to fill in a
		map while waiting for a higher resolution tile'''
		if tile.zoom == self.min_zoom:
			return None

		# find the equivalent lower res tile
		(lat,lon) = tile.coord()

		width2 = TILES_WIDTH
		height2 = TILES_HEIGHT

		for zoom2 in range(tile.zoom-1, self.min_zoom-1, -1):
			width2 /= 2
			height2 /= 2

			if width2 == 0 or height2 == 0:
				break

			tile_info = self.coord_to_tile(lat, lon, zoom2)

			# see if its in the tile cache
			key = tile_info.key()
			if key in self._tile_cache:
				img = self._tile_cache[key]
				if img == self._unavailable:
					continue
			else:
				path = self.tile_to_path(tile_info)
				try:
					img = cv.LoadImage(path)
					# add it to the tile cache
					self._tile_cache[key] = img
					while len(self._tile_cache) > self.cache_size:
						self._tile_cache.popitem(0)
				except IOError as e:
					continue

			# copy out the quadrant we want
			cv.SetImageROI(img, (tile_info.offsetx, tile_info.offsety, width2, height2))
			img2 = cv.CreateImage((width2,height2), 8, 3)
			cv.Copy(img, img2)
			cv.ResetImageROI(img)

			# and scale it
			scaled = cv.CreateImage((TILES_WIDTH, TILES_HEIGHT), 8, 3)
			cv.Resize(img2, scaled)
			#cv.Rectangle(scaled, (0,0), (255,255), (0,255,0), 1)
			return scaled
		return None

	def load_tile(self, tile):
		'''load a tile from cache or tile server'''

		# see if its in the tile cache
		key = tile.key()
		if key in self._tile_cache:
			img = self._tile_cache[key]
			if img == self._unavailable:
				img = self.load_tile_lowres(tile)
				if img is None:
					img = cv.LoadImage(self._unavailable)
				return img			
				

		path = self.tile_to_path(tile)
		try:
			ret = cv.LoadImage(path)
			# add it to the tile cache
			self._tile_cache[key] = ret
			while len(self._tile_cache) > self.cache_size:
				self._tile_cache.popitem(0)
			return ret
		except IOError as e:
			if not e.errno in [errno.ENOENT]:
				raise
			pass
		if not self.download:
			img = self.load_tile_lowres(tile)
			if img is None:
				img = cv.LoadImage(self._unavailable)
			return img			

		try:
			self._download_pending[key].refresh_time()
		except Exception:
			self._download_pending[key] = tile
		self.start_download_thread()

		img = self.load_tile_lowres(tile)
		if img is None:
			img = cv.LoadImage(self._loading)
		return img
	

	def scaled_tile(self, tile):
		'''return a scaled tile'''
		width = int(TILES_WIDTH / tile.scale)
		height = int(TILES_HEIGHT / tile.scale)
		scaled_tile = cv.CreateImage((width,height), 8, 3)
		full_tile = self.load_tile(tile)
		cv.Resize(full_tile, scaled_tile)
		return scaled_tile


	def coord_from_area(self, x, y, lat, lon, width, ground_width):
		'''return (lat,lon) for a pixel in an area image'''

		pixel_width = ground_width / float(width)
		dx = x * pixel_width
		dy = y * pixel_width

		return mp_util.gps_offset(lat, lon, dx, -dy)


	def coord_to_pixel(self, lat, lon, width, ground_width, lat2, lon2):
		'''return pixel coordinate (px,py) for position (lat2,lon2)
		in an area image. Note that the results are relative to top,left
		and may be outside the image'''
		pixel_width = ground_width / float(width)

		if lat is None or lon is None or lat2 is None or lon2 is None:
			return (0,0)
			
		dx = mp_util.gps_distance(lat, lon, lat, lon2)
		if lon2 < lon:
			dx = -dx
		dy = mp_util.gps_distance(lat, lon, lat2, lon)
		if lat2 > lat:
			dy = -dy

		dx /= pixel_width
		dy /= pixel_width
		return (int(dx), int(dy))
		

	def area_to_tile_list(self, lat, lon, width, height, ground_width, zoom=None):
		'''return a list of TileInfoScaled objects needed for
		an area of land, with ground_width in meters, and
		width/height in pixels.

		lat/lon is the top left corner. If unspecified, the
		zoom is automatically chosen to avoid having to grow
		the tiles
		'''

		pixel_width = ground_width / float(width)
		ground_height = ground_width * (height/(float(width)))
		top_right = mp_util.gps_newpos(lat, lon, 90, ground_width)
		bottom_left = mp_util.gps_newpos(lat, lon, 180, ground_height)
		bottom_right = mp_util.gps_newpos(bottom_left[0], bottom_left[1], 90, ground_width)

		# choose a zoom level if not provided
		if zoom is None:
			zooms = list(range(self.min_zoom, self.max_zoom+1))
		else:
			zooms = [zoom]
		for zoom in zooms:
			tile_min = self.coord_to_tile(lat, lon, zoom)
			(twidth,theight) = tile_min.size()
			tile_pixel_width = twidth / float(TILES_WIDTH)
			scale = pixel_width / tile_pixel_width
			if scale >= 1.0:
				break

		scaled_tile_width = int(TILES_WIDTH / scale)
		scaled_tile_height = int(TILES_HEIGHT / scale)

		# work out the bottom right tile
		tile_max = self.coord_to_tile(bottom_right[0], bottom_right[1], zoom)

		ofsx = int(tile_min.offsetx / scale)
		ofsy = int(tile_min.offsety / scale)
		srcy = ofsy
		dsty = 0

		ret = []

		# place the tiles
		for y in range(tile_min.y, tile_max.y+1):
			srcx = ofsx
			dstx = 0
			for x in range(tile_min.x, tile_max.x+1):
				if dstx < width and dsty < height:
					ret.append(TileInfoScaled((x,y), zoom, scale, (srcx,srcy), (dstx,dsty)))
				dstx += scaled_tile_width-srcx
				srcx = 0
			dsty += scaled_tile_height-srcy
			srcy = 0
		return ret

	def area_to_image(self, lat, lon, width, height, ground_width, zoom=None, ordered=True):
		'''return an RGB image for an area of land, with ground_width 
		in meters, and width/height in pixels.

		lat/lon is the top left corner. The zoom is automatically
		chosen to avoid having to grow the tiles'''

		img = cv.CreateImage((width,height),8,3)

		tlist = self.area_to_tile_list(lat, lon, width, height, ground_width, zoom)

		# order the display by distance from the middle, so the download happens
		# close to the middle of the image first
		if ordered:
			(midlat, midlon) = self.coord_from_area(width/2, height/2, lat, lon, width, ground_width)
			tlist.sort(key=lambda d: d.distance(midlat, midlon), reverse=True)
		
		for t in tlist:
			scaled_tile = self.scaled_tile(t)

			w = min(width - t.dstx, scaled_tile.width - t.srcx)
			h = min(height - t.dsty, scaled_tile.height - t.srcy)
			if w > 0 and h > 0:
				cv.SetImageROI(scaled_tile, (t.srcx, t.srcy, w, h))
				cv.SetImageROI(img, (t.dstx, t.dsty, w, h))
				cv.Copy(scaled_tile, img)
				cv.ResetImageROI(img)
				cv.ResetImageROI(scaled_tile)

		# return as an RGB image
		cv.CvtColor(img, img, cv.CV_BGR2RGB)
		return img


if __name__ == "__main__":

	from optparse import OptionParser
	parser = OptionParser("mp_tile.py [options]")
	parser.add_option("--lat", type='float', default=-35.362938, help="start latitude")
	parser.add_option("--lon", type='float', default=149.165085, help="start longitude")
	parser.add_option("--width", type='float', default=1000.0, help="width in meters")
	parser.add_option("--service", default="YahooSat", help="tile service")
	parser.add_option("--zoom", default=None, type='int', help="zoom level")
	parser.add_option("--max-zoom", type='int', default=19, help="maximum tile zoom")
	parser.add_option("--delay", type='float', default=1.0, help="tile download delay")
	parser.add_option("--boundary", default=None, help="region boundary")
	parser.add_option("--debug", action='store_true', default=False, help="show debug info")
	(opts, args) = parser.parse_args()

	lat = opts.lat
	lon = opts.lon
	ground_width = opts.width
	
	if opts.boundary:
		boundary = mp_util.polygon_load(opts.boundary)
		bounds = mp_util.polygon_bounds(boundary)
		lat = bounds[0]+bounds[2]
		lon = bounds[1]
		ground_width = max(mp_util.gps_distance(lat, lon, lat, lon+bounds[3]),
				   mp_util.gps_distance(lat, lon, lat-bounds[2], lon))
		print(lat, lon, ground_width)

	mt = MPTile(debug=opts.debug, service=opts.service,
		    tile_delay=opts.delay, max_zoom=opts.max_zoom)
	if opts.zoom is None:
		zooms = list(range(mt.min_zoom, mt.max_zoom+1))
	else:
		zooms = [opts.zoom]
	for zoom in zooms:
		tlist = mt.area_to_tile_list(lat, lon, width=1024, height=1024,
					     ground_width=ground_width, zoom=zoom)
		print(("zoom %u needs %u tiles" % (zoom, len(tlist))))
		for tile in tlist:
			mt.load_tile(tile)
		while mt.tiles_pending() > 0:
			time.sleep(2)
			print(("Waiting on %u tiles" % mt.tiles_pending()))
	print('Done')
