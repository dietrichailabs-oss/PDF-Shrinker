from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).resolve().parent / "pdf_shrinker.ico"
SIZE = 256

image = Image.new("RGBA", (SIZE, SIZE), "#07111f")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((38, 20, 194, 232), radius=18, fill="#f4f7fb")
draw.polygon([(154, 20), (194, 60), (154, 60)], fill="#c6d1dc")
draw.rounded_rectangle((54, 99, 178, 153), radius=10, fill="#e44444")

try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
except OSError:
    font = ImageFont.load_default()

box = draw.textbbox((0, 0), "PDF", font=font)
width = box[2] - box[0]
draw.text(((SIZE - width) / 2 - 12, 105), "PDF", font=font, fill="white")

draw.polygon([(202, 99), (232, 128), (202, 157), (202, 140), (217, 128), (202, 116)], fill="#9eff3c")
draw.polygon([(31, 99), (1, 128), (31, 157), (31, 140), (16, 128), (31, 116)], fill="#9eff3c")

image.save(
    OUTPUT,
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print(f"Created {OUTPUT}")
