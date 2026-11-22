from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "rahasia-finance-tracker-lokal-2026"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

DB_NAME = "finance.db"


@app.route('/manifest.json')
def manifest():
    return send_from_directory('.', 'manifest.json')


@app.route('/sw.js')
def service_worker():
    return send_from_directory('.', 'sw.js')


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            jenis TEXT NOT NULL,
            jumlah INTEGER NOT NULL,
            kategori TEXT NOT NULL,
            catatan TEXT,
            tanggal TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kategori TEXT NOT NULL,
            batas_nominal INTEGER NOT NULL,
            UNIQUE(user_id, kategori),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tabungan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nama_tujuan TEXT NOT NULL,
            target_nominal INTEGER NOT NULL,
            terkumpul INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.template_filter('rupiah')
def format_rupiah(angka):
    if angka is None:
        return "0"
    return f"{int(angka):,}".replace(",", ".")


# HALAMAN LOGIN & DAFTAR AKUN
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    mode = request.form.get('mode', 'login') if request.method == 'POST' else request.args.get('mode', 'login')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        nama = request.form.get('nama', '').strip()

        conn = get_db()
        cur = conn.cursor()

        if mode == 'register':
            if not nama or not username or not password:
                error = "Nama, username, dan password wajib diisi."
            else:
                hashed_pw = generate_password_hash(password)
                try:
                    cur.execute(
                        "INSERT INTO users (nama, username, password) VALUES (?, ?, ?)",
                        (nama, username, hashed_pw)
                    )
                    conn.commit()
                    user = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                    session.permanent = True
                    session['user_id'] = user['id']
                    session['nama_user'] = user['nama']
                    conn.close()
                    return redirect(url_for('index'))
                except sqlite3.IntegrityError:
                    error = "Username sudah digunakan. Silakan pilih username lain."
        else:
            user = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session.permanent = True
                session['user_id'] = user['id']
                session['nama_user'] = user['nama']
                conn.close()
                return redirect(url_for('index'))
            else:
                error = "Username atau password salah."

        conn.close()

    return render_template('login.html', error=error, mode=mode)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# 1. HALAMAN DASHBOARD (BERANDA)
@app.route('/')
@login_required
def index():
    user_id = session['user_id']
    nama_user = session.get('nama_user', 'Pengguna')

    conn = get_db()
    bulan_ini = datetime.now().strftime('%Y-%m')
    minggu_lalu = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    # Saldo Saat Ini
    total_masuk_all = conn.execute(
        "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pemasukan'", (user_id,)
    ).fetchone()[0] or 0
    total_keluar_all = conn.execute(
        "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pengeluaran'", (user_id,)
    ).fetchone()[0] or 0
    saldo = total_masuk_all - total_keluar_all

    # Pemasukan & Pengeluaran Bulan Ini
    masuk_bulan = conn.execute(
        "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pemasukan' AND tanggal LIKE ?",
        (user_id, f'{bulan_ini}%')
    ).fetchone()[0] or 0
    keluar_bulan = conn.execute(
        "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pengeluaran' AND tanggal LIKE ?",
        (user_id, f'{bulan_ini}%')
    ).fetchone()[0] or 0

    # Data Notifikasi: Total pengeluaran 7 hari terakhir
    keluar_minggu_ini = conn.execute(
        "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pengeluaran' AND tanggal >= ?",
        (user_id, minggu_lalu)
    ).fetchone()[0] or 0

    # 5 Transaksi Terakhir
    transaksi_terakhir = conn.execute(
        "SELECT * FROM transaksi WHERE user_id=? ORDER BY tanggal DESC, id DESC LIMIT 5",
        (user_id,)
    ).fetchall()

    # Data Grafik 7 Hari Terakhir
    hari_labels = []
    data_masuk_grafik = []
    data_keluar_grafik = []
    nama_hari = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min']

    for i in range(6, -1, -1):
        tgl = (datetime.now() - timedelta(days=i))
        tgl_str = tgl.strftime('%Y-%m-%d')
        hari_labels.append(nama_hari[tgl.weekday()])

        m = conn.execute(
            "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pemasukan' AND tanggal=?",
            (user_id, tgl_str)
        ).fetchone()[0] or 0
        k = conn.execute(
            "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pengeluaran' AND tanggal=?",
            (user_id, tgl_str)
        ).fetchone()[0] or 0
        data_masuk_grafik.append(m)
        data_keluar_grafik.append(k)

    conn.close()
    return render_template(
        'index.html',
        nama_user=nama_user,
        saldo=saldo,
        masuk_bulan=masuk_bulan,
        keluar_bulan=keluar_bulan,
        keluar_minggu_ini=keluar_minggu_ini,
        transaksi_terakhir=transaksi_terakhir,
        hari_labels=hari_labels,
        data_masuk_grafik=data_masuk_grafik,
        data_keluar_grafik=data_keluar_grafik
    )


# 2. HALAMAN TAMBAH TRANSAKSI
@app.route('/tambah', methods=['GET', 'POST'])
@login_required
def tambah():
    user_id = session['user_id']
    if request.method == 'POST':
        jenis = request.form['jenis']
        jumlah = int(request.form['jumlah'])
        kategori = request.form['kategori']
        catatan = request.form['catatan']
        tanggal = request.form['tanggal']

        conn = get_db()
        conn.execute(
            'INSERT INTO transaksi (user_id, jenis, jumlah, kategori, catatan, tanggal) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, jenis, jumlah, kategori, catatan, tanggal)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    hari_ini = datetime.now().strftime('%Y-%m-%d')
    return render_template('tambah.html', hari_ini=hari_ini, nama_user=session.get('nama_user', 'Pengguna'))


# EDIT TRANSAKSI
@app.route('/transaksi/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_transaksi(id):
    user_id = session['user_id']
    conn = get_db()

    transaksi_item = conn.execute(
        'SELECT * FROM transaksi WHERE id = ? AND user_id = ?',
        (id, user_id)
    ).fetchone()

    if not transaksi_item:
        conn.close()
        return redirect(url_for('riwayat'))

    if request.method == 'POST':
        jenis = request.form['jenis']
        jumlah = int(request.form['jumlah'])
        kategori = request.form['kategori']
        catatan = request.form['catatan']
        tanggal = request.form['tanggal']

        conn.execute(
            '''
            UPDATE transaksi
            SET jenis = ?, jumlah = ?, kategori = ?, catatan = ?, tanggal = ?
            WHERE id = ? AND user_id = ?
            ''',
            (jenis, jumlah, kategori, catatan, tanggal, id, user_id)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('riwayat'))

    conn.close()
    return render_template(
        'edit_transaksi.html',
        t=transaksi_item,
        nama_user=session.get('nama_user', 'Pengguna')
    )


# HAPUS TRANSAKSI
@app.route('/transaksi/hapus/<int:id>', methods=['POST'])
@login_required
def hapus_transaksi(id):
    user_id = session['user_id']
    conn = get_db()
    conn.execute(
        'DELETE FROM transaksi WHERE id = ? AND user_id = ?',
        (id, user_id)
    )
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('riwayat'))


# 3. HALAMAN STATISTIK & BUDGET
@app.route('/budget', methods=['GET', 'POST'])
@login_required
def budget():
    user_id = session['user_id']
    conn = get_db()
    bulan_ini = datetime.now().strftime('%Y-%m')

    if request.method == 'POST':
        kategori = request.form['kategori']
        batas = int(request.form['batas_nominal'])
        existing = conn.execute(
            "SELECT id FROM budget WHERE user_id=? AND kategori=?", (user_id, kategori)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE budget SET batas_nominal=? WHERE id=? AND user_id=?",
                (batas, existing['id'], user_id)
            )
        else:
            conn.execute(
                "INSERT INTO budget (user_id, kategori, batas_nominal) VALUES (?, ?, ?)",
                (user_id, kategori, batas)
            )
        conn.commit()
        conn.close()
        return redirect(url_for('budget'))

    pengeluaran_kategori = conn.execute('''
        SELECT kategori, SUM(jumlah) as total
        FROM transaksi
        WHERE user_id=? AND jenis='pengeluaran' AND tanggal LIKE ?
        GROUP BY kategori
    ''', (user_id, f'{bulan_ini}%')).fetchall()

    labels_kategori = [row['kategori'] for row in pengeluaran_kategori]
    values_kategori = [row['total'] for row in pengeluaran_kategori]
    total_pengeluaran_bulan = sum(values_kategori)

    daftar_budget = conn.execute('SELECT * FROM budget WHERE user_id=?', (user_id,)).fetchall()
    data_budget = []
    for b in daftar_budget:
        terpakai = conn.execute(
            "SELECT SUM(jumlah) FROM transaksi WHERE user_id=? AND jenis='pengeluaran' AND kategori=? AND tanggal LIKE ?",
            (user_id, b['kategori'], f'{bulan_ini}%')
        ).fetchone()[0] or 0
        persen = min(round((terpakai / b['batas_nominal']) * 100), 100) if b['batas_nominal'] > 0 else 0
        data_budget.append({
            'id': b['id'],
            'kategori': b['kategori'],
            'batas': b['batas_nominal'],
            'terpakai': terpakai,
            'persen': persen
        })

    conn.close()
    return render_template(
        'budget.html',
        data_budget=data_budget,
        labels_kategori=labels_kategori,
        values_kategori=values_kategori,
        total_pengeluaran_bulan=total_pengeluaran_bulan,
        nama_user=session.get('nama_user', 'Pengguna')
    )


# 4. HALAMAN TABUNGAN (SAVING GOALS)
@app.route('/tabungan', methods=['GET', 'POST'])
@login_required
def tabungan():
    user_id = session['user_id']
    conn = get_db()
    if request.method == 'POST':
        aksi = request.form.get('aksi')
        if aksi == 'buat':
            nama = request.form['nama_tujuan']
            target = int(request.form['target_nominal'])
            conn.execute(
                'INSERT INTO tabungan (user_id, nama_tujuan, target_nominal, terkumpul) VALUES (?, ?, ?, 0)',
                (user_id, nama, target)
            )
        elif aksi == 'tambah_saldo':
            id_tab = request.form['id']
            tambah_uang = int(request.form['nominal_tambah'])
            conn.execute(
                'UPDATE tabungan SET terkumpul = terkumpul + ? WHERE id = ? AND user_id = ?',
                (tambah_uang, id_tab, user_id)
            )
        conn.commit()
        conn.close()
        return redirect(url_for('tabungan'))

    daftar_tabungan = conn.execute('SELECT * FROM tabungan WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    return render_template('tabungan.html', daftar_tabungan=daftar_tabungan, nama_user=session.get('nama_user', 'Pengguna'))


# RUTE HAPUS TABUNGAN
@app.route('/tabungan/hapus/<int:id>', methods=['POST'])
@login_required
def hapus_tabungan(id):
    user_id = session['user_id']
    conn = get_db()
    conn.execute('DELETE FROM tabungan WHERE id = ? AND user_id = ?', (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('tabungan'))


# RUTE EDIT TABUNGAN
@app.route('/tabungan/edit/<int:id>', methods=['POST'])
@login_required
def edit_tabungan(id):
    user_id = session['user_id']
    nama_tujuan = request.form['nama_tujuan']
    target_nominal = int(request.form['target_nominal'])
    terkumpul = int(request.form['terkumpul'])

    conn = get_db()
    conn.execute(
        'UPDATE tabungan SET nama_tujuan = ?, target_nominal = ?, terkumpul = ? WHERE id = ? AND user_id = ?',
        (nama_tujuan, target_nominal, terkumpul, id, user_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('tabungan'))


# 5. HALAMAN RIWAYAT & FILTER
@app.route('/riwayat')
@login_required
def riwayat():
    user_id = session['user_id']
    conn = get_db()
    q = request.args.get('q', '')
    kategori = request.args.get('kategori', '')
    tanggal = request.args.get('tanggal', '')

    query = "SELECT * FROM transaksi WHERE user_id = ?"
    params = [user_id]

    if q:
        query += " AND (catatan LIKE ? OR kategori LIKE ?)"
        params.extend([f'%{q}%', f'%{q}%'])
    if kategori:
        query += " AND kategori = ?"
        params.append(kategori)
    if tanggal:
        query += " AND tanggal = ?"
        params.append(tanggal)

    query += " ORDER BY tanggal DESC, id DESC"
    semua_transaksi = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        'riwayat.html',
        transaksi=semua_transaksi,
        q=q,
        kategori=kategori,
        tanggal=tanggal,
        nama_user=session.get('nama_user', 'Pengguna')
    )


init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)