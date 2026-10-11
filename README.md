# teams-notifier

Microsoft Teams sınıflarına (ekiplerine) yeni dosya yüklendiğinde telefona [ntfy](https://ntfy.sh) ile
bildirim gönderen küçük bir Python aracı. Teams, sınıflara yüklenen dosyalar için bildirim vermiyor; bu araç
o boşluğu kapatıyor.

> **Kimler kullanabilir?** Proje **İYTE (İzmir Yüksek Teknoloji Enstitüsü) Microsoft 365 Education**
> hesabıyla geliştirildi ve orada test edildi. Aynı Teams/Microsoft 365 yapısını kullanan her okulda
> çalışması beklenir; çalışıp çalışmayacağını okulun izin politikası belirler (bkz.
> [İzinler](#izinler-ve-sınırlar)). Başka bir okulda denersen sonucu issue olarak paylaşabilirsin.

Araç **hiçbir yapay zekâ/LLM servisi kullanmaz**. Çalışır, birkaç saniyede biter, kapanır: yalnızca
Microsoft Graph ve ntfy'ye HTTP istekleri yapar. Sürekli çalışan bir süreç veya sunucu yoktur.

## Durum

| Özellik | Durum |
|---|---|
| Yeni dosya bildirimi (ilk taramada bildirim yok, sonra yalnızca yeniler) | ✅ Çalışıyor |
| `status`, `test-notify`, `run --dry-run` | ✅ Çalışıyor |
| Ödev hatırlatmaları ve günlük özet | 🚧 Planlandı (okul yöneticisi onayı gerekiyor) |
| Gönderi (post) bildirimleri | 🚧 Planlandı (okul yöneticisi onayı gerekiyor) |
| Zamanlanmış görev kurulumu (`install_task.ps1`) | 🚧 Planlandı |
| Otomatik dosya indirme | 🚧 Planlandı, varsayılan kapalı |

## Kurulum

Gereksinimler: Windows, Python 3.11+, telefonda [ntfy uygulaması](https://ntfy.sh/).

```powershell
git clone https://github.com/<kullanici-adin>/teams-notifier
cd teams-notifier
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m teams_notifier setup
```

`setup` sırayla şunları yapar:

1. Tahmin edilemez uzun bir ntfy topic'i üretir ve config dosyasını yazar.
2. Topic'i gösterir; ntfy uygulamasında bu topic'e abone olursun.
3. Okul hesabınla *device code* ile giriş yaptırır (tarayıcıda kod girersin).
4. Deneme bildirimi gönderir.
5. Mevcut dosyaları "görüldü" diye kaydeder; bunlar için bildirim **gönderilmez**.

Sonra elle ya da zamanlayıcıyla:

```powershell
.\.venv\Scripts\python.exe -m teams_notifier run
```

### Komutlar

| Komut | Ne yapar |
|---|---|
| `setup` | İlk kurulum |
| `login [--with-posts]` | Giriş / yeniden giriş |
| `run [--dry-run]` | Yeni dosyaları kontrol et ve bildir. `--dry-run` bildirim göndermez, durumu değiştirmez |
| `test-notify` | Deneme bildirimi |
| `status` | Oturum, takip edilen dersler, modül durumları |

## Ayarlar

Config ve veriler proje klasöründe değil, `%LOCALAPPDATA%\teams-notifier\` içinde durur
(`TEAMS_NOTIFIER_HOME` ortam değişkeniyle değiştirilebilir). Tüm seçenekler için
[config.example.toml](config.example.toml) dosyasına bak.

## Güvenlik

- **ntfy topic'i bir paroladır.** ntfy.sh'de topic'e abone olan herkes mesajları okuyabilir; bu yüzden
  topic rastgele ve uzun üretilir. Kimseyle paylaşma, bu repoya ekleme.
- Oturum (yenileme) token'ı Windows DPAPI ile **şifreli** saklanır. Şifreleme kurulamazsa açık metne
  düşülmez, araç hata verir.
- Araç yalnızca **okuma** çağrıları yapar. Token yalnızca `graph.microsoft.com` adresine gönderilir.
- Loglara token ve delta bağlantıları yazılmaz.

## İzinler ve sınırlar

Araç, Microsoft'un birinci taraf **"Microsoft Graph Command Line Tools"** istemci kimliğini kullanır;
kendi uygulama kaydı yoktur. Bu kimlik İYTE kiracısında önceden onaylı olduğu için `User.Read` ve
`Team.ReadBasic.All` ile sınıf listesi ve dosya değişiklikleri yönetici onayı olmadan okunabiliyor.

- Ödevler (`EduAssignments.ReadBasic`) ve kanal mesajları (`ChannelMessage.Read.All`) İYTE'de yönetici
  onayı istiyor. Bu araç yönetici onayını **aşmaya çalışmaz**; ilgili özellikler config'te kapalıdır.
- Kendi okulunda denemeden önce okulun BT/kullanım politikasını kontrol et. Okulun Entra kayıtlarında
  giriş denemeleri uygulama adıyla görünür.
- Kendi uygulama kaydını kullanmak istersen config'te `[auth] client_id` değerini ver.

## Geliştirme

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Lisans

[MIT](LICENSE)
