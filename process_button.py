import os
from PIL import Image

def process_button():
    src_path = r'C:\Users\MY PC\.gemini\antigravity\brain\10df6316-5cdd-49a9-b28d-18b78c45c548\arrow_line_icon_1771735907411.png'
    target_path = r'assets/image_part_4.png'
    output_path = r'assets/end_button.png'

    # Load source image (the newly generated icon)
    src_img = Image.open(src_path).convert('RGBA')

    # Remove background
    datas = src_img.getdata()
    bg_color = datas[0]
    new_data = []
    tolerance = 25
    for item in datas:
        if (abs(item[0] - bg_color[0]) <= tolerance and
            abs(item[1] - bg_color[1]) <= tolerance and
            abs(item[2] - bg_color[2]) <= tolerance):
            new_data.append((255, 255, 255, 0)) # transparent
        else:
            new_data.append(item)
    src_img.putdata(new_data)

    # Load target image to match size
    try:
        target_img = Image.open(target_path)
        target_size = target_img.size
    except FileNotFoundError:
        # Fallback if target is unexpectedly missing
        target_size = (170, 144)

    # Calculate scaling factor to fit inside target size with some padding
    # Let's say we want the icon to take up 60% of the height
    target_icon_height = int(target_size[1] * 0.6)
    scale_factor = target_icon_height / src_img.height
    new_width = int(src_img.width * scale_factor)
    
    src_resized = src_img.resize((new_width, target_icon_height), Image.Resampling.LANCZOS)

    # Create new blank transparent image of target size
    final_img = Image.new('RGBA', target_size, (255, 255, 255, 0))

    # Calculate center position to paste
    paste_x = (target_size[0] - new_width) // 2
    paste_y = (target_size[1] - target_icon_height) // 2

    # Paste the resized icon
    final_img.paste(src_resized, (paste_x, paste_y), src_resized)

    # Save
    final_img.save(output_path, 'PNG')
    print(f"Successfully saved to {output_path} with size {target_size}")

if __name__ == '__main__':
    process_button()
