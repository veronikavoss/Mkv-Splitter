import os
from PIL import Image

icons = [
    'assets/play_icon.png',
    'assets/pause_icon.png',
    'assets/start_button.png',
    'assets/end_button.png'
]

target_size = (170, 144)
# 상하 각각 12px 여백 -> 사용 가능한 높이는 144 - 24 = 120
target_h = 120

for icon in icons:
    if not os.path.exists(icon):
        print(f"Skipping {icon}, not found.")
        continue
        
    # 이미지를 열고 RGBA 모드로 변환
    img = Image.open(icon).convert("RGBA")
    
    # 투명도가 아닌 실제 그림이 있는 영역의 경계 상자를 가져옴
    bbox = img.getbbox()
    if not bbox:
        print(f"Empty image {icon}")
        continue
        
    # 그림 부분만 정확히 잘라냄
    cropped = img.crop(bbox)
    
    # 높이 120px에 맞춰 비율을 유지하며 새로운 너비 계산
    scale = target_h / cropped.height
    new_w = int(cropped.width * scale)
    
    # 크기 조정 (안티앨리어싱 품질 유지)
    resized = cropped.resize((new_w, target_h), Image.Resampling.LANCZOS)
    
    # 170x144 크기의 투명한 새 캔버스 생성
    new_img = Image.new("RGBA", target_size, (255, 255, 255, 0))
    
    # 캔버스 중앙 정렬 좌표 계산 (상하 여백은 무조건 12px)
    paste_x = (target_size[0] - new_w) // 2
    paste_y = 12
    
    # 리사이즈된 이미지를 투명 캔버스에 붙여넣기
    new_img.paste(resized, (paste_x, paste_y), resized)
    
    # 동일한 이름으로 덮어쓰기 저장
    new_img.save(icon, "PNG")
    print(f"Processed {icon}: {new_w}x{target_h}, margin_y={paste_y}")

print("All icons have been standardized with 12px top/bottom margins.")
