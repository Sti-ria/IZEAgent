import os

# 获取当前程序所在的文件夹
folder_path = os.path.dirname(os.path.abspath(__file__))
os.chdir(folder_path)

print(f"当前工作目录: {folder_path}")

# 1. 获取所有 png 文件 (忽略已经改名好的 puffshroom_ 开头的文件)
files = [f for f in os.listdir('.') if f.lower().endswith('.png')]

# 排序，保证顺序一致
files.sort()

if not files:
    print("错误：在这个文件夹里没有找到任何 .png 图片！")
    print("请确保这个 .py 文件和图片放在同一个文件夹下。")
else:
    print(f"共找到 {len(files)} 个图片，准备开始重命名...")
    
    count = 1
    for filename in files:
        if count<10:
            new_name = f"puffshroom_00{count}.png"
        elif count<100:
            new_name = f"puffshroom_0{count}.png"
        else:
            new_name = f"puffshroom_{count}.png"
        
        # 执行重命名
        try:
            os.rename(filename, new_name)
            print(f"成功: {filename} -> {new_name}")
            count += 1
        except Exception as e:
            print(f"失败: 无法重命名 {filename}，原因: {e}")

    print("\n--- 所有任务处理完毕！---")

# 这行代码很重要，防止窗口闪退，让你能看到结果
input("按回车键退出程序...")