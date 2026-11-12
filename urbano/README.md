# Cuencas urbanas — generador de datos

Pipeline que construye el grafo vial (calles → cruces → enlaces) de una ciudad y lo
empaqueta en el binario que consume el HTML de «Cuencas urbanas».

## Por qué existe

El HTML publicado es un único fichero con los datos comprimidos en base64 dentro de
`<script id="citydata">`. Para añadir una ciudad hay que generar exactamente el mismo
formato: cabecera JSON + arrays tipados empaquetados.

## Formato

```
[uint32 n][JSON cabecera][padding a 8][payload de arrays]
```

Cada ciudad de la cabecera lleva `arrays: [[clave, dtype, offset, tamaño], …]` con
offsets relativos al inicio del payload. Arrays:

| clave | tipo | significado |
|---|---|---|
| jx, jy | int16 | coordenadas del cruce en metros (origen `lon0`/`lat0`) |
| jw | float32 | km de calle que drena el cruce (mitad de los enlaces adyacentes) |
| lu, lv | uint32 | cruce origen / destino del enlace |
| lk | uint16 | longitud del enlace en metros |
| tf, tb | uint16 | segundos en sentido u→v y v→u (0 = prohibido) |
| lname | uint16 | índice en `names`, 65535 = sin nombre |
| gcnt | uint16 | puntos de la geometría del enlace |
| gsx, gsy | int16 | primer punto de la geometría |
| gd | int16 | deltas (x,y) entre puntos consecutivos |

`extent` (opcional, añadido aquí) fija el encuadre del póster: caja [x0,y0,x1,y1] con
el 86 % de los km de calle, para que los términos municipales alargados (Valencia,
Málaga, Zaragoza) no dejen medio lienzo vacío. Sin `extent` se usa el bbox del límite
municipal, como en Madrid y Barcelona.

## Uso

```bash
cd scripts
python build.py valencia sevilla           # descarga OSM (cache/) y construye
python encode.py ../data/original.html ../out/cuencas.html valencia sevilla
python verify.py ../out/cuencas.html ../out/verify.json   # chrome-headless
```

- `build.py` cachea todo en `cache/` (`<slug>_boundary.json`, `<slug>_ways.json`,
  `<slug>_districts.json`, `<slug>_built.json`); se puede relanzar sin volver a descargar.
- Overpass va rotando entre espejos (`z.`, `lz4.`, `overpass-api.de`, mail.ru,
  private.coffee) porque los 502/504 son habituales.
- `encode.py` añade las ciudades al binario original sin tocar Madrid ni Barcelona.

## Datos

- Calles: © OpenStreetMap (ODbL).
- Tipos incluidos: motorway…tertiary, unclassified, residential, living_street,
  pedestrian y service (sin aparcamientos ni accesos privados).
- Velocidad: `maxspeed` si existe; si no, por tipo de vía (110/90/70/60/50/40/30/15/10/5).
- Tiempos teóricos, sin tráfico ni semáforos.
