
$(function(){
  window.Mavelous = window.Mavelous || {};

  Mavelous.MMapModel = Backbone.Model.extend({
    WIDE_ZOOM: 2,
    TIGHT_ZOOM: 16,
    gotgps: false,

    defaults: function () {
      return { lat: 0, lon: 0, zoom: this.WIDE_ZOOM };
    },

    validate: function ( attrs ) {
      if ( attrs.zoom > 18 ) return "zoom too high";
      if ( attrs.zoom < 1 )  return "zoom too low";
    },

    initialize: function () {
      var mavlink = this.get('mavlinkSrc');
      this.gotgps = false;
      this.gps = mavlink.subscribe('GPS_RAW_INT', this.onGps, this);
    },

    onGps: function () {
      var gpslat = this.gps.get('lat');
      var gpslon = this.gps.get('lon');
      var state = { lat: gpslat / 1.0e7, lon: gpslon / 1.0e7 };

      if ( gpslat !== 0 && gpslon !== 0 && this.gotgps === false ) {
        this.gotgps = true;
        state.zoom = this.TIGHT_ZOOM;
      }
      this.set(state);
    },

    zoomBy: function (delta) {
      this.set('zoom', this.get('zoom') + parseFloat(delta));
    },

    setZoom: function (z) {
      this.set('zoom', parseFloat(z));
    },

    getZoom: function () {
      return this.get('zoom');
    }
  });
});

