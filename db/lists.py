def get(connection, music_id):
    rows = []
    for row in connection.execute('SELECT LISTS.Name FROM '
                                  'MUSIC JOIN LISTS, LISTITEMS '
                                  'ON LISTS.Id = LISTITEMS.ListId AND '
                                  'LISTITEMS.MusicID = MUSIC.Id WHERE MUSIC.ID = %d' % music_id):
        rows.append(row[0])
    return rows
