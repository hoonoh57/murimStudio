from app.services.image_generator import ImageGenerator
gen = ImageGenerator()
imgs = gen.get_images_for_script(18)
print(f"개수: {len(imgs)}")
print(f"타입: {type(imgs[0])}")
print(f"값: {imgs[0]}")
