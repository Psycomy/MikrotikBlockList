# Static data of the lookup page

- `land-110m.json`: the land shape from [world-atlas](https://github.com/topojson/world-atlas)
  2.0.2, unchanged (`land-110m.json` on jsDelivr). world-atlas is ISC-licensed
  (`world-atlas.LICENSE`); its shapes come from [Natural Earth](https://www.naturalearthdata.com/),
  which is in the public domain.
- `centroids.json`: ISO 3166-1 alpha-2 code → `[lon, lat]` (degrees, 2 decimals), where the
  comet of a listed IP starts. Derived from Natural Earth admin-0 (public domain) via world-atlas
  2.0.2 `countries-50m.json`:
  - each country's point is the spherical centroid (d3-geo `geoCentroid`) of its largest
    polygon, so overseas territories do not pull it into the sea;
  - ISO numeric ids are mapped to alpha-2 codes with the Debian `iso-codes` table
    (`iso_3166-1.json`); Kosovo, which has no ISO numeric id, is `XK` as DB-IP uses it;
  - 14 codes that have no own shape at that scale (BQ BV CC CX GF GI GP MQ RE SJ TK TV UM YT)
    were added by hand from their approximate main-island or capital coordinates.

  A country missing from the table gets a comet from a random land point.
