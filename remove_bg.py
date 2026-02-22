from PIL import Image

def make_transparent(img_path):
    img = Image.open(img_path).convert("RGBA")
    datas = img.getdata()
    # Assume the top left pixel is the background color
    bg_color = datas[0]
    
    new_data = []
    tolerance = 20  # You can adjust this tolerance
    for item in datas:
        # Check if pixel is within the tolerance range of the background color
        if (abs(item[0] - bg_color[0]) <= tolerance and
            abs(item[1] - bg_color[1]) <= tolerance and
            abs(item[2] - bg_color[2]) <= tolerance):
            # Change it to fully transparent
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
            
    img.putdata(new_data)
    img.save(img_path, "PNG")

if __name__ == "__main__":
    make_transparent("assets/play_icon.png")
    make_transparent("assets/pause_icon.png")
    print("Backgrounds removed.")
