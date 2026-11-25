# NAKS — No API Key System

[English README](README.md)

Bu araç projelerde geliştirme yaparken yapay zekâ çağrıları için API token'ı harcamanı engeller. Kod API'yi çağırmaz. Onun yerine soruyu NAKS'a sorar ve NAKS cevabı aboneliğinden getirir. Cevabı getirmenin iki yolu var:

- **Sohbet (`chat`):** İstek bir dosyaya yazılır. Claude sohbetinde `/naks` dediğinde Claude bekleyen istekleri cevaplar.
- **Claude Code (`cli`):** İstek anında `claude -p` ile cevaplanır. Bu yol günlük bir sınırla korunur.

Her cevap kaydedilir ve aynı soru bir daha sorulmaz. API anahtarı gerekmez. Production'a geçerken tek bir ortam değişkenini değiştirirsin.

```
kodun ──ask()──▶ .naks/requests/<id>.json        (bekliyor)
                          │
              sohbette /naks  ──▶  Claude cevaplar
                          │
kodun ◀──ask()── .naks/responses/<id>.json       (önbellek: aynı istek bir daha sorulmaz)
```

## Kurulum

Projeyi NAKS'a bağlamanın iki yolu var.

**1. Kodu hiç değiştirmeden (`naks-dev`).** Proje resmi Anthropic ya da OpenAI SDK'sını kullanıyorsa komutunun başına `naks-dev` eklemen yeterli:

```bash
git clone https://github.com/genceumut/naks ~/naks
export PATH="$HOME/naks/bin:$PATH"   # shell profiline ekle

cd projen
naks-dev npm run dev
NAKS_MODE=cli naks-dev python3 generate.py
```

`naks-dev` yerel bir endpoint (`naks serve`) başlatır. SDK'ları `ANTHROPIC_BASE_URL` ve `OPENAI_BASE_URL` değişkenleriyle o endpoint'e yönlendirir. Komut bitince endpoint'i kapatır. Proje gerçek bir API'yle konuştuğunu sanır. Endpoint'i ayrıca kendin de çalıştırabilirsin: `python3 ~/naks/python/naks_serve.py`, sonra SDK'da `base_url = "http://127.0.0.1:4141"` (OpenAI için `/v1` ekle) ve `api_key = "naks"`.

Endpoint şunları destekler: `/v1/messages`, `/v1/chat/completions`, streaming, base64 görseller, JSON şeması ve tek bir tool ile yapılandırılmış çıktı. Birden fazla tool ile gerçek tool döngüleri, embedding ve ses desteklenmez. `chat` modunda istek açık kalır (en fazla `NAKS_SERVE_WAIT` = 540 saniye). Sen `/naks` deyince cevap aynı isteğe döner. Süre dolarsa 424 hatası döner. SDK'lar bu hatayı otomatik tekrar denemez.

**2. Kodda `ask()` ile.** SDK kullanmayan ya da yeni yazdığın projelerde tek dosyayı projene kopyala. Başka bağımlılık yok:

- Python: `python/naks_client.py`
- JS/TS (Node 18+): `js/naks-client.mjs` (tipler: `js/naks-client.d.mts`)

## Kullanım

```python
from naks_client import ask, NaksPending

try:
    title = ask("Bu not için 5 kelimelik başlık öner:\n" + note, task="note-title")
    tags = ask("Bu nottan etiket çıkar.", inputs={"note": note},
               schema={"type": "array", "items": {"type": "string"}}, task="tags")
except NaksPending as e:
    print(e)   # "2 istek cevap bekliyor… Claude sohbetinde /naks de"
```

```js
import { ask } from "./naks-client.mjs";
const tags = await ask("Bu nottan etiket çıkar.", { inputs: { note }, schema: { type: "array", items: { type: "string" } }, task: "tags" });
```

Tipik döngü şöyle işler:
1. Kodu çalıştırırsın. Cevabı olmayan istekler yazılır ve `NaksPending` hatası gelir.
2. Claude sohbetinde `/naks` dersin. İstersen proje adını da eklersin: `/naks yarun`.
3. Kodu tekrar çalıştırırsın. Cevaplar artık diskten gelir.

Prompt'u, sistem mesajını, girdileri ya da şemayı değiştirirsen istek id'si de değişir. Yeni istek yeniden sorulur. Hiçbir şey değişmezse istek bir daha sorulmaz.

Görsel ya da PDF göndermek için `files` kullan (png, jpg, gif, webp, pdf). Dosyanın içeriği değişirse istek de yeni sayılır:

```python
desc = ask("Bu slaytı tek cümleyle özetle.", files=["pages/p3.png"], task="slide-summary")
```

Toplu iş için önce hepsini yaz, sonra oku:

```python
from naks_client import submit, get, pending
ids = [submit(f"Şu yorumu sınıflandır: {r}", schema=SCHEMA, task="review-class") for r in reviews]
# /naks
results = [get(i) for i in ids]
```

## Modlar

`NAKS_MODE` ortam değişkeniyle seçilir. `api` dışındaki her mod önce önbelleğe bakar. Cevap kayıtlıysa hiçbir yere gidilmez.

| Mod | Cevap yoksa ne olur | Ne zaman |
|---|---|---|
| `chat` (varsayılan) | İstek dosyaya yazılır, `NaksPending` gelir. Sohbette `/naks` dersin | Toplu işler, görsel içeren istekler |
| `cli` | `claude -p` ile anında cevaplanır (aboneliğinden) | Geliştirirken küçük, tek tek gelen sorular |
| `record` | Gerçek API çağrılır, cevap kaydedilir | Gerçek modelin cevabını bir kez alıp saklamak için |
| `replay` | `NaksMissing` hatası gelir, yeni soru sorulmaz | Testler ve CI |
| `api` | Önbelleğe bakılmadan doğrudan gerçek API çağrılır | Production |

**`cli` modunun güvenlik önlemleri.** `claude -p` her seferinde araçları kapalı, boş bir geçici klasörde ve oturum kaydetmeden çalışır, yani sadece metin üretir. Ortamdaki `ANTHROPIC_API_KEY` çağrı sırasında silinir, böylece yanlışlıkla API'ye fatura çıkmaz. Günde en fazla `NAKS_CLI_DAILY_LIMIT` (20) çağrı yapılır, sayaç `.naks/cli-usage.json` dosyasında tutulur. Bütün çağrılar `.naks/cli-log.jsonl` dosyasına loglanır. Aşağıdaki durumlarda istek kendiliğinden `chat` yoluna düşer ve `/naks`'a kalır:
- Günlük sınır dolmuşsa
- İstekte görsel ya da PDF varsa
- `claude` kurulu değilse
- `claude -p` iki denemede de hata verirse ya da cevap şemaya uymazsa

`cli` modunu kişisel geliştirme için kullan. Zamanlanmış görevlere ya da sürekli çalışan gözetimsiz işlere bağlama.

| Ortam değişkeni | Varsayılan | Ne yapar |
|---|---|---|
| `NAKS_WAIT` | `0` | `chat` modunda cevap yoksa kaç saniye dosya yoklansın |
| `NAKS_DIR` | proje kökü/.naks | `.naks` klasörünün yeri (`.git` ya da `.naks` içeren ilk üst klasör) |
| `NAKS_MODEL` | `claude-sonnet-5-5` | `api` ve `record` modlarında model |
| `NAKS_CLI_DAILY_LIMIT` | `20` | `cli` modunda günlük en fazla `claude -p` çağrısı |
| `NAKS_CLI_TIMEOUT` | `180` | Tek bir `claude -p` çağrısı için saniye |
| `NAKS_CLI_MODEL` | Claude Code'un varsayılanı | `cli` modunda model |
| `NAKS_PORT` | `4141` | `naks serve` portu |
| `NAKS_SERVE_WAIT` | `540` | `naks serve`'ün `chat` modunda bir cevabı bekleme süresi (saniye) |

`.gitignore` önerisi: `.naks/cli-usage.json`, `.naks/cli-log.jsonl`, `.naks/*.tmp`.

## Mevcut projeyi NAKS'a çevirmek: `/naksify`

Proje resmi SDK kullanıyorsa önce `naks-dev` ile dene, çoğu zaman kopyaya gerek kalmaz. `/naksify <proje>` ise projenin bir kopyasını oluşturur. Bütün kopyalar tek bir klasörde toplanır: `~/Projects/naks-at-your-service/<proje>/`. Kopyadaki yapay zekâ çağrılarını `ask()` ile değiştirir, API anahtarı gerektiren kodu kaldırır ve kopyanın köküne ne yapıldığını anlatan bir `NAKS.md` yazar. Orijinal projeye dokunulmaz. Kopyadaki bekleyen istekler için `/naks <proje>` demen yeterli. `/naksify github <repo>` aynı işi repoda `naks` adlı bir branch açarak yapar.

## GitHub'daki projeler

Bir projenin `.naks/requests/` klasörünü commit'leyip push'larsan `/naks github <repo>` komutu repoyu okur, cevapları `.naks/responses/` altına yazar ve senin adınla commit'leyip push'lar. Sonra sen `git pull` yaparsın.

## Skill'ler

`skill/naks/SKILL.md` (bekleyen istekleri cevaplar) ve `skill/naksify/SKILL.md` (projenin NAKS kopyasını çıkarır) dosyaları İngilizce şablonlardır. Klasör yolunu ve GitHub kullanıcı adını kendine göre düzenleyip Claude'a skill olarak ekleyebilirsin.

## Protokol

`.naks/requests/<id>.json`:

```json
{
  "naks": 1,
  "id": "tags-3f2a9c1b7d4e",
  "project": "yarun",
  "task": "tags",
  "created_at": "2026-11-24T10:45:00+00:00",
  "system": "İsteğe bağlı sistem mesajı",
  "prompt": "Bu nottan etiket çıkar.",
  "inputs": { "note": "..." },
  "output": { "format": "json", "schema": { "type": "array", "items": { "type": "string" } } }
}
```

Ek varsa istek bir de `"files": [{"path": "pages/p1.png", "sha256": "…"}]` alanı taşır. Yol proje köküne göredir.

`output.format` alanı `text`, `markdown` ya da `json` olabilir. Şema verilmişse varsayılan `json` olur. Id, `task` alanının ASCII hali ile `system`, `prompt`, `inputs` ve `output` alanlarının SHA-256 özetinin ilk 12 karakterinden oluşur. Python ve JS istemcileri aynı id'yi üretir.

`.naks/responses/<id>.json`:

```json
{ "naks": 1, "id": "tags-3f2a9c1b7d4e", "answered_at": "…", "answered_by": "claude-chat", "output": ["iş", "toplantı"] }
```

`answered_by` alanı cevabın nereden geldiğini gösterir: `claude-chat` (`/naks`), `claude-cli` (`cli` modu) ya da `api:<model>` (`record` modu). `naks serve` üzerinden gelen istekler `serve-anthropic-…` ve `serve-openai-…` id'leri alır. İsteğe görev adı vermek istersen `X-NAKS-Task` başlığını gönder. Base64 görseller `.naks/files/` altına kaydedilir.

İstek cevaplanamazsa `output` yerine `"error": "neden"` yazılır.

## Kullanım şartları ve sorumlu kullanım

NAKS, tüketici aboneliklerinin kullanım kurallarında temkinli tarafta kalacak şekilde tasarlandı:
- **Kimlik bilgisi yeniden kullanılmaz.** NAKS hiçbir zaman OAuth token'ı ya da web oturumu kopyalamaz veya taşımaz. Bir sohbet arayüzünü de otomatikleştirmez. Cevaplar iki yoldan gelir: senin resmi bir Claude uygulamasında çalışman (`chat`) ya da kendi makinendeki resmi Claude Code CLI (`cli`).
- **Sadece kişisel geliştirme için.** Son kullanıcı trafiğini NAKS'tan geçirme, bir aboneliği birden fazla kişiyle paylaşma ve NAKS'ı bir servis olarak çalıştırma. Production'da kendi API anahtarınla `NAKS_MODE=api` kullan.
- **`cli` modunu ölçülü kullan.** Anthropic'in yardım merkezi, Kasım 2026 itibarıyla `claude -p` kullanımının abonelik limitlerinden düştüğünü söylüyor ([kaynak](https://support.claude.com/en/articles/15036540)). Bu konudaki kurallar 2026'da birkaç kez değişti. Güncel [kullanım şartlarını](https://www.anthropic.com/legal/consumer-terms) kendin kontrol et ve `cli` modunu zamanlanmış ya da gözetimsiz işlere bağlama.

NAKS'ı kendi hesaplarınla nasıl kullandığından sen sorumlusun. Bu proje Anthropic ya da OpenAI ile bağlantılı değildir.

## Sınırlar

- Sohbetteki Claude ham API çağrısıyla birebir aynı çıktıyı vermez. Ara çıktılar, test verisi, sınıflandırma ve taslak işleri için yeterlidir. Production prompt'unu ince ayarlarken son denemeleri `NAKS_MODE=api` ile yap.
- `chat` modu gerçek zamanlı değildir. Cevap ancak sen `/naks` dediğinde gelir. Anında cevap için `cli` modunu kullan.
- `cli` modu ham API ile aynı değildir: `temperature` gibi parametreler yoktur ve her çağrıda birkaç saniye ek gecikme olur. Anthropic'in abonelik kuralları 2026'da birkaç kez değişti. Bu modu ölçülü kullan.
- Kişisel geliştirme aracıdır. Son kullanıcı trafiği hiçbir zaman bu yoldan geçmemeli.
