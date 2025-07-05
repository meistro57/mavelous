const path = require('path');
const webpack = require('webpack');

module.exports = {
  mode: 'development',
  entry: './modules/lib/mmap_app/src/index.mjs',
  output: {
    path: path.resolve(__dirname, 'modules/lib/mmap_app/dist'),
    filename: 'bundle.js',
  },
  plugins: [
    new webpack.ProvidePlugin({
      $: 'jquery',
      jQuery: 'jquery',
      Backbone: 'backbone',
      _: 'underscore'
    })
  ],
  resolve: {
    fallback: {
      fs: false,
      path: false
    }
  }
};
