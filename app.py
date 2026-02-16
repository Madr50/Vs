import pyfiglet

def show_love():
    # اختيار نوع الخط المزخرف (هنا استخدمنا 'slant' ويمكنك تجربة 'block')
    big_text = pyfiglet.figlet_format("I LOVE YOU", font="slant")
    print(big_text)
    
    # إضافة لمسة جمالية بسيطة باللغة العربية
    print("      ♥ أحبـــــك ♥      ")

if __name__ == "__main__":
    show_love()
