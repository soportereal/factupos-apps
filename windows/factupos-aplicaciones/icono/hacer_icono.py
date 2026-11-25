from PIL import Image, ImageDraw
S = 1024
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
# fondo: cuadrado redondeado azul FactuPOS con un degradé suave (arriba más claro)
base = Image.new("RGBA", (S, S))
bd = ImageDraw.Draw(base)
top, bot = (25, 55, 109), (11, 36, 71)
for y in range(S):
    t = y / S
    bd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=210, fill=255)
im.paste(base, (0, 0), mask)
# cuadrícula 3x3 de «apps»: 8 blancas y 1 celeste (la que se está instalando)
m, g = 230, 52
cel = (S - 2 * m - 2 * g) / 3
colores = {(2, 2): (56, 189, 248, 255)}
for f in range(3):
    for c in range(3):
        x0 = m + c * (cel + g); y0 = m + f * (cel + g)
        d.rounded_rectangle([x0, y0, x0 + cel, y0 + cel], radius=int(cel * 0.26), fill=colores.get((f, c), (255, 255, 255, 255)))
# flecha de descarga sobre la celda celeste
x0 = m + 2 * (cel + g); y0 = m + 2 * (cel + g); cx = x0 + cel / 2
w = cel * 0.14
d.rectangle([cx - w / 2, y0 + cel * 0.18, cx + w / 2, y0 + cel * 0.58], fill=(11, 36, 71, 255))
d.polygon([(cx - cel * 0.28, y0 + cel * 0.48), (cx + cel * 0.28, y0 + cel * 0.48), (cx, y0 + cel * 0.80)], fill=(11, 36, 71, 255))
im.save("aplicaciones.png")
im.save("aplicaciones.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
im.resize((128,128), Image.LANCZOS).save("vista128.png")
im.resize((32,32), Image.LANCZOS).resize((128,128), Image.NEAREST).save("vista32.png")
