import os


class PlayListCreator(object):
    def __init__(self, destination_dir):
        self.destination_dir = destination_dir
        self.lists_by_name = {}

    def add(self, lists, file_info):
        for l in lists:
            if l not in self.lists_by_name:
                self.lists_by_name[l] = []
            self.lists_by_name[l].append(file_info)

    def create_m3u(self):
        for k in self.lists_by_name.keys():
            with open(os.path.join(self.destination_dir, '{name}.m3u'.format(name=k)), "w") as f:
                f.write("#EXTM3U\n")
                for file_info in self.lists_by_name[k]:
                    f.write(u'#EXTINFO:{len},{name}\n'.format(**file_info).encode('utf-8'))
                    f.write(u'{file_path}\n'.format(**file_info).encode('utf-8'))
