# NAKS kurulumu

Bu rehber seni sıfırdan, yapay zekâ çağrılarını Claude aboneliğinden cevaplayan bir projeye kadar götürür. Komutlar macOS ve Linux içindir. Windows'ta WSL kullan.

[English](INSTALL.md) · [README'ye dön](README.tr.md)

**İçindekiler**
1. [Temel kontroller](#1-temel-kontroller)
2. [NAKS'ı indir](#2-naksı-indir)
3. [Demoyu dene](#3-demoyu-dene)
4. [Claude skill'lerini kur](#4-claude-skilllerini-kur) (sohbet modu için)
5. [Claude Code'u kur](#5-claude-codeu-kur) (cli modu için)
6. [İlk projeni bağla](#6-ilk-projeni-bağla)
7. [Sorun giderme](#7-sorun-giderme)
8. [Kaldırma](#8-kaldırma)

4. ve 5. adımların ikisi birden gerekmez. Sohbet modu için 4. adım, cli modu için 5. adım yeterli. Diğerini sonra da ekleyebilirsin.

---

## 1. Temel kontroller

```bash
python3 --version   # 3.9 ya da daha yeni
git --version
node --version      # sadece JavaScript istemcisini kullanacaksan (18 ya da daha yeni)
```

Bir Claude planın da olmalı (Pro, Max, Team, …).

## 2. NAKS'ı indir

NAKS'ı projelerini tuttuğun klasöre klonla. Bu rehber `~/Projects` kullanıyor. Seninki farklıysa aşağıdaki her yerde kendi yolunu kullan.

```bash
mkdir -p ~/Projects
git clone https://github.com/genceumut/naks ~/Projects/naks
```

**İsteğe bağlı: `naks-dev`'i her yerden kullanılabilir yap.** Bu adım olmadan `naks-dev`'i tam yoluyla çalıştırırsın (`~/Projects/naks/bin/naks-dev`). Bu adımla sadece `naks-dev` yazman yeter:

```bash
echo 'export PATH="$HOME/Projects/naks/bin:$PATH"' >> ~/.zshrc   # bash kullanıyorsan ~/.bashrc
source ~/.zshrc
naks-dev        # şunu yazmalı: Usage: naks-dev <command> [args] ...
```

## 3. Demoyu dene

```bash
cd ~/Projects/naks
python3 examples/demo.py
```

`2 request(s) queued in .naks/requests/` mesajını görmelisin. NAKS iki soruyu kaydetti ve cevap bekliyor. 4. ve 5. adımlar bu soruları cevaplamanın iki yolunu kuruyor.

## 4. Claude skill'lerini kur

*Sohbet modu için gerekli.* Sohbet modunda bekleyen soruları bir Claude sohbetinde `/naks` yazarak cevaplarsın. Bunun için Claude'un `/naks` skill'ine ve projeler klasörüne erişime ihtiyacı var.

**a. Claude masaüstü uygulamasını** [claude.ai/download](https://claude.ai/download) adresinden kur ve giriş yap.

**b. Claude'a projeler klasörünü ver.** Masaüstü uygulamasında bir sohbette **+** menüsünden **Add folder**'ı seç ve `~/Projects` klasörünü göster. Bu adımı atlarsan da sorun olmaz: `/naks`'ı ilk çalıştırdığında Claude klasöre erişim ister.

**c. Skill şablonlarını doldur.** `skill/naks/SKILL.md` ve `skill/naksify/SKILL.md` dosyalarını aç. Her birinin başında şunları ayarla:
- `PROJECTS`: projeler klasörün (`~/Projects`)
- `GITHUB_OWNER`: GitHub kullanıcı adın (sadece `/naks github …` için)
- `NAKS_HOME`: NAKS'ın yeri (`~/Projects/naks`, sadece naksify'da)

**d. Her skill'i bir ZIP dosyası yap.** Claude, ZIP'in en üstünde skill'in klasörünü bekler:

```bash
cd ~/Projects/naks/skill
zip -r naks.zip naks
zip -r naksify.zip naksify
```

**e. Yükle.** Claude'da **Customize → Skills** bölümüne git. **+** düğmesine bas, sonra **Create skill → Upload** de ve `naks.zip` dosyasını seç. Aynısını `naksify.zip` için tekrarla. İkisinin de açık olduğundan emin ol.

**f. Demoyu cevapla.** Claude masaüstü uygulamasında bir sohbete şunu yaz:

```
/naks naks
```

Claude bekleyen iki soruyu bulur, cevaplar ve cevap dosyalarını yazar. Sonra:

```bash
python3 examples/demo.py   # artık başlığı ve etiketleri yazar
```

Bir kez daha çalıştır: cevaplar diskten anında gelir, hiçbir model çağrılmaz.

## 5. Claude Code'u kur

*Cli modu için gerekli.* Cli modunda NAKS soruları senin makinende Claude Code'u (`claude -p`) çalıştırarak anında cevaplar.

**a. Claude Code'u kur:**

```bash
curl -fsSL https://claude.ai/install.sh | bash
# ya da Homebrew ile:  brew install --cask claude-code
```

Yeni bir terminal aç ve kontrol et: `claude --version`.

**b. Claude hesabınla giriş yap.** `claude` komutunu bir kez çalıştır ve API anahtarıyla değil, Claude aboneliğinle giriş yapmayı seç. Sonra `/exit` ile çık.

**c. NAKS üzerinden dene:**

```bash
cd ~/Projects/naks
NAKS_MODE=cli python3 -c "import sys; sys.path.insert(0, 'python'); from naks_client import ask; print(ask('Say hello in exactly 3 words', task='hello'))"
```

Birkaç saniye içinde üç kelimelik bir cevap gelmeli. Tekrar çalıştırırsan cevap diskten hemen gelir. NAKS çağrıları `.naks/cli-usage.json` dosyasında sayar (varsayılan sınır günde 20, `NAKS_CLI_DAILY_LIMIT` ile değiştirebilirsin).

> NAKS, Claude Code'un ortamından `ANTHROPIC_API_KEY` değişkenini siler. Böylece anahtar shell'inde tanımlı olsa bile cli modu yanlışlıkla API hesabına fatura çıkaramaz.

## 6. İlk projeni bağla

Önce projenin bir LLM'i resmi SDK'larla çağırıp çağırmadığına bak:

```bash
cd ~/Projects/projen
grep -rn --include='*.py' --include='*.ts' --include='*.js' -E 'anthropic|openai' . --exclude-dir=node_modules | head
```

**`anthropic` / `@anthropic-ai/sdk` / `openai` kullanıyorsa kod değişikliği gerekmez.** Her zamanki komutunu `naks-dev` ile çalıştır:

```bash
naks-dev npm run dev                        # sohbet modu
NAKS_MODE=cli naks-dev python3 main.py      # cli modu
```

Sohbet modunda SDK çağrısı beklerken açık kalır. Claude'da `/naks projen` yazarsın ve çağrı cevapla döner. 9 dakika içinde kimse cevaplamazsa çağrı HTTP 424 ile biter, soru daha sonra cevaplanmak üzere kuyrukta kalır.

Projenin `.gitignore` dosyasına şu satırları ekle:

```
.naks/cli-usage.json
.naks/cli-log.jsonl
.naks/*.tmp
```

**Başka bir şey kullanıyorsa (kendi HTTP istemcisi, LangChain, …) ya da yeni kod yazıyorsan:** `python/naks_client.py` ya da `js/naks-client.mjs` dosyasını projeye kopyala ve `ask()` çağır. Ayrıntılar [README](README.tr.md#yol-2-koddan-çağırmak-ask)'de. Ya da Claude'a `/naksify projen` yaz, dönüşümü bir kopya üzerinde o yapsın.

**Production'da** `ask()` kullanıyorsan `NAKS_MODE=api` (ve `ANTHROPIC_API_KEY`) ayarla. SDK kullanıyorsan `naks-dev`'i hiç kullanma.

## 7. Sorun giderme

| Sorun | Çözüm |
|---|---|
| `naks-dev: command not found` | [2. adımdaki](#2-naksı-indir) isteğe bağlı PATH ayarını yap ya da tam yolu kullan: `~/Projects/naks/bin/naks-dev`. |
| `NaksPending: … request(s) waiting` | Sohbet modunda bu beklenen bir durum. Claude'a `/naks <proje>` yaz, sonra tekrar çalıştır. |
| `/naks` bekleyen soru bulamıyor | Claude'un doğru klasöre erişimi olduğundan ve skill'deki `PROJECTS` değerinin o klasörle eşleştiğinden emin ol. Sorular `<proje>/.naks/requests/` altında durur. |
| `[naks] cli unavailable (claude not found …)` | Claude Code'u kur ([5. adım](#5-claude-codeu-kur)) ve yeni bir terminal aç. |
| `[naks] cli unavailable (daily cap reached …)` | Günlük sınır doldu, soru `/naks` için kuyruğa alındı. Gerekirse `NAKS_CLI_DAILY_LIMIT` değerini artır. |
| `[naks] cli unavailable (claude -p failed: …)` | `claude` komutunu bir kez çalıştır ve Claude hesabınla giriş yaptığından emin ol. |
| `Address already in use` / port 4141 dolu | Başka bir `naks serve` çalışıyor (`naks-dev` onu kullanır) ya da `NAKS_PORT=4142` ayarla. |
| SDK'dan HTTP 424 | Sohbet modu `/naks` için çok uzun bekledi. Soru hâlâ kuyrukta: cevapla ve tekrar çalıştır. Daha uzun beklemek için `NAKS_SERVE_WAIT` değerini artır. |
| SDK hâlâ gerçek API'yi çağırıyor | Projede `base_url` / `baseURL` koda sabit yazılmış. Onu kaldır ya da `ask()` / `/naksify` kullan. |
| `HTTP 400 … tool loops with multiple tools are not supported` | Proje çok tool'lu gerçek bir ajan döngüsü çalıştırıyor, bu desteklenmiyor. O kısım için `record` modunu kullan. |

## 8. Kaldırma

```bash
rm -rf ~/Projects/naks
# eklediysen PATH satırını ~/.zshrc (ya da ~/.bashrc) dosyasından sil
# kayıtlı cevapları istemiyorsan projelerindeki .naks/ klasörlerini sil
```

Skill'leri Claude'da **Customize → Skills** altından kaldır.
