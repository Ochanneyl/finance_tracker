import sqlite3

def init_db():
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()

    # 1. Tabel Transaksi
    c.execute('''
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jenis TEXT NOT NULL,          -- 'pemasukan' atau 'pengeluaran'
            jumlah INTEGER NOT NULL,
            kategori TEXT NOT NULL,
            catatan TEXT,
            tanggal TEXT NOT NULL         -- Format: YYYY-MM-DD
        )
    ''')

    # 2. Tabel Budget (Batas Pengeluaran per Kategori)
    c.execute('''
        CREATE TABLE IF NOT EXISTS budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kategori TEXT UNIQUE NOT NULL,
            batas_nominal INTEGER NOT NULL
        )
    ''')

    # 3. Tabel Tabungan (Saving Goals)
    c.execute('''
        CREATE TABLE IF NOT EXISTS tabungan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_tujuan TEXT NOT NULL,
            target_nominal INTEGER NOT NULL,
            terkumpul INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()
    print("Database finance.db berhasil dibuat!")

if __name__ == '__main__':
    init_db()