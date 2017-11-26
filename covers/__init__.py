import os


def file_get_contents(filename):
    with open(filename) as f:
        return f.read()

def has_cover(path):
    file_list = os.listdir(path)
    return 'cover.jpg' in file_list or 'cover.png' in file_list


def cover(path):
    jpg_cover = os.path.join(path, 'cover.jpg')
    png_cover = os.path.join(path, 'cover.png')
   
    if os.path.exists(jpg_cover):
        return file_get_contents(jpg_cover), 'jpeg'
    elif os.path.exists(png_cover):
        return file_get_contents(png_cover), 'png'
    else:
        return None, None
