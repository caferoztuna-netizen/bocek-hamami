# -*- coding: utf-8 -*-
"""
BÖCEK HAMAMI — YAYIN İSTASYONU
Bilgisayarda çalışır, iPhone'dan yayın yapmayı sağlar:
  1) Oyunu ev Wi-Fi'ı üzerinden telefona sunar      → http://<bilgisayar-ip>:8080/?yayin=1
  2) TikFinity'nin olaylarını telefona iletir         → ws://<bilgisayar-ip>:21214  (→ 127.0.0.1:21213)
  3) Telefonun okutacağı QR kodlu bağlantı sayfasını açar → http://localhost:8080/baglan
Sadece ev ağındaki (özel IP'li) cihazlara hizmet verir; yalnızca oyun dosyalarını paylaşır.
Kapatmak için bu pencereyi kapat (ya da Ctrl+C).
"""
import ipaddress
import os
import socket
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HTTP_PORT = 8080
RELAY_PORT = 21214
TIKFINITY = ('127.0.0.1', 21213)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))  # paket gönderilmez; sadece çıkış arayüzünü bulur
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def is_local_client(addr):
    try:
        ip = ipaddress.ip_address(addr)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


IP = lan_ip()
GAME_URL = f'http://{IP}:{HTTP_PORT}/?yayin=1'

BAGLAN_HTML = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><title>Böcek Hamamı — Telefonu Bağla</title>
<style>
 body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#1b1512;color:#f5ecdf;font-family:'Segoe UI',sans-serif}
 .card{background:#2a211c;border:1px solid #6b5137;border-radius:22px;padding:30px 36px;max-width:560px;box-shadow:0 20px 60px #0008}
 h1{margin:0 0 6px;color:#fbbf24;font-size:26px}
 #qr{background:#fff;padding:16px;border-radius:14px;display:inline-block;margin:18px 0}
 code{background:#00000055;padding:4px 8px;border-radius:8px;color:#fde68a;font-size:15px}
 ol{line-height:1.7;padding-left:20px} .ok{color:#4ade80} .bad{color:#f87171}
</style></head><body><div class="card">
<h1>Böcek Hamamı · Yayın İstasyonu</h1>
<div>Durum: TikFinity <b id="tf">kontrol ediliyor…</b></div>
<div id="qr"></div>
<div>Ya da Safari'ye yaz: <code>__URL__</code></div>
<ol>
 <li>iPhone bu bilgisayarla <b>aynı Wi-Fi</b>'da olsun.</li>
 <li>iPhone kamerasıyla QR kodu okut → Safari'de aç.</li>
 <li>Paylaş ⬆️ → <b>Ana Ekrana Ekle</b> (bir kez yeterli), sonra ana ekrandaki <b>Böcek Hamamı</b> simgesinden aç.</li>
 <li>Ekrana bir kez dokun, oyun başlasın.</li>
 <li>TikTok → + → CANLI → <b>Mobil oyun / Ekran paylaşımı</b> ile yayını başlat, sonra Böcek Hamamı'na geç.</li>
</ol>
</div>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
 new QRCode(document.getElementById('qr'), { text: '__URL__', width: 280, height: 280, correctLevel: QRCode.CorrectLevel.M });
 const tf = document.getElementById('tf');
 const ws = new WebSocket('ws://localhost:21213/');
 ws.onopen = () => { tf.textContent = 'bağlı ✓'; tf.className = 'ok'; ws.close(); };
 ws.onerror = () => { tf.textContent = 'kapalı — TikFinity uygulamasını aç'; tf.className = 'bad'; };
</script></body></html>"""


class GameHandler(SimpleHTTPRequestHandler):
    ALLOWED_PREFIXES = ('/assets/',)
    ALLOWED_FILES = {'/', '/index.html', '/favicon.ico'}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        pass  # sessiz

    def _deny(self):
        self.send_error(404)

    def do_GET(self):
        if not is_local_client(self.client_address[0]):
            return self._deny()
        path = self.path.split('?', 1)[0]
        if path == '/baglan':
            body = BAGLAN_HTML.replace('__URL__', GAME_URL).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in self.ALLOWED_FILES or (path.startswith(self.ALLOWED_PREFIXES) and '..' not in path):
            return super().do_GET()
        return self._deny()

    def end_headers(self):
        # Telefon her açılışta oyunun en güncel halini alsın
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()


def relay_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', RELAY_PORT))
    srv.listen(16)
    while True:
        client, addr = srv.accept()
        if not is_local_client(addr[0]):
            client.close()
            continue
        try:
            upstream = socket.create_connection(TIKFINITY, timeout=5)
            upstream.settimeout(None)
        except OSError:
            print('  ! TikFinity\'ye bağlanılamadı — TikFinity açık mı?', flush=True)
            client.close()
            continue
        print(f'  → {addr[0]} oyunu TikFinity\'ye bağladı', flush=True)
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()


def main():
    try:
        httpd = ThreadingHTTPServer(('0.0.0.0', HTTP_PORT), GameHandler)
    except OSError:
        print(f'Port {HTTP_PORT} kullanımda. İstasyon zaten açık olabilir.')
        input('Kapatmak için Enter...')
        return
    threading.Thread(target=relay_server, daemon=True).start()
    print('=' * 60)
    print('  BÖCEK HAMAMI · YAYIN İSTASYONU ÇALIŞIYOR')
    print('=' * 60)
    print(f'  Telefonda açılacak adres : {GAME_URL}')
    print(f'  QR kodlu sayfa           : http://localhost:{HTTP_PORT}/baglan')
    print('  Yayın bitince bu pencereyi kapat.')
    print('-' * 60, flush=True)
    if '--no-browser' not in sys.argv:
        webbrowser.open(f'http://localhost:{HTTP_PORT}/baglan')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
