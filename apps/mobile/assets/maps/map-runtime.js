// MapLibre's Flutter adapter omits the public pixelRatio/context options.
// Draw vector geometry and glyphs at >=2 physical pixels per logical pixel,
// including on desktop previews reporting DPR=1. This does not scale labels
// or fetch raster images at another geographic zoom.
(() => {
  const Map = window.maplibregl.Map;
  window.maplibregl.Map = class ChargeGridMap extends Map {
    constructor(options) {
      super({
        ...options,
        pixelRatio: Math.max(2, window.devicePixelRatio || 1),
        canvasContextAttributes: {
          ...options.canvasContextAttributes,
          antialias: true,
        },
      });
    }
  };
})();
