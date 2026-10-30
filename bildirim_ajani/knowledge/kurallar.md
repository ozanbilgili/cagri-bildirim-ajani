# Müşteri Bildirim Raporu — İş Birimi Kural Kitabı

Bu doküman Örnek Portföy Müşteri İletişim Merkezi'nin aylık bildirim raporunu doldururken
uygulanan iş birimi kurallarını içerir. Her `###` başlığı bir kuraldır; başlıktaki ön ek
kuralın hangi rapor alanına ait olduğunu gösterir:
G = genel, D = Bildirim Türü, K = Bildirimin Konusu, I = Muhatap Kurum, J = Fon Kodu,
L = Bildirim Detayı, E = Bildirim Sahibi.

## Genel kurallar

### G-1 Girdi biçimi ve kişisel veri
Girdi, müşteri telefon görüşmesinin transkriptidir. Konuşmacılar `TEMSİLCİ:` ve `MÜŞTERİ:`
(rol bilinmiyorsa `KONUŞMACI 1:` / `KONUŞMACI 2:`) olarak işaretlenir. Telefon, TC kimlik
ve IBAN maskelenmiş olabilir (`[TELEFON]`, `[TCKN]`, `[IBAN]`); bunları ad ya da numara sanma.

### G-2 Kanıt zorunluluğu
Her alan transkriptteki bir kanıta dayanmalıdır. Kanıt yoksa tahmin etme; alanın
"belirsiz" karşılığını seç (fon kodu için "-", bildirim sahibi için boş, konu için "Diğer")
ve güven puanını düşük ver.

### G-3 Arayanın kurumu muhatap değildir
Arayan kişinin nerede çalıştığı ya da kim adına aradığı muhatabı belirlemez. Muhatap,
konuşulan ürün veya hizmetin sahibidir.

## D — Bildirim Türü

### D-1 Şikayet en yüksek önceliktir
Müşteri ağzından şu sinyallerden biri geçiyorsa tür "Şikayet"tir: şikayet etmek,
memnun değilim, memnuniyetsizlik, rahatsızlık; zarar ettim, para kaybettim; çalışmıyor,
açılmıyor, hata veriyor, donuyor; alamıyorum/satamıyorum (çözülmemiş sorun tonunda);
getiri yok, performans düşük, hayal kırıklığı; yanlış yönlendirme, ilgisizlik, cevap
alamamak; mağduriyet, haksızlık, yanıltıcı bilgi. Temsilci sorunu çözmüş olsa bile müşteri
şikayet diliyle aradıysa tür "Şikayet"tir.

### D-2 Dolandırıcılık her zaman şikayettir
Dolandırıcılık, sahte hesap, sahte WhatsApp grubu, kimlik avı, "kandırıldım" gibi güvenlik
olayları her zaman "Şikayet" olarak sınıflanır ve bildirim detayında mutlaka belirtilir.

### D-3 Şikayet sinyali müşteriye ait olmalıdır
Şikayet sinyali MÜŞTERİNİN ifadesinde geçmelidir. Temsilcinin "memnuniyetsizlik yaşamamanız
için" gibi kalıp cümleleri ya da anlatıcı klişeleri şikayet sayılmaz. Mevzuat veya tanım
değişikliği sorusu (ör. nitelikli yatırımcı tanımı) memnuniyetsizlik dili yoksa
"Bilgi Talebi"dir.

### D-4 Öneri
Şikayet yoksa ve müşteri açıkça öneri iletiyorsa tür "Öneri"dir: "öneriyorum", "önerim var",
"... olsa iyi olur", "... eklenirse sevinirim", "yeni fon çıkarılsın". DİKKAT: "yatırım önerisi
istiyorum" öneri DEĞİLDİR; müşteri tavsiye istiyordur, tür "Bilgi Talebi"dir.

### D-5 Beğeni/Teşekkür
Şikayet ve öneri yoksa, aramanın ASIL amacı teşekkür veya takdir ise "Beğeni/Teşekkür"dür.
Görüşme sonundaki kapanış nezaketi ("teşekkür ederim, iyi günler") beğeni sayılmaz.
Konuşmada soru veya talep de varsa asıl amaca göre sınıfla.

### D-6 Hat Kesildi
Anlamlı konuşma hiç oluşmadıysa (ses gelmedi, bağlantı koptu, müşteri konuşmadan kapandı)
tür "Hat Kesildi"dir. Konuşma başlayıp bir talep ortaya çıktıysa, sonradan kesilse bile
içeriğe göre sınıfla.

### D-7 Konudan türe varsayılan eşleme
Yukarıdakilerden hiçbiri yoksa: konu "Fon Getirilerinin Düşüklüğü" ise tür "Şikayet";
konu "Fonlar ve Hizmetlerimiz Hakkında Bilgi", "Alım/Satım Esasları/Operasyonel Süreç",
"Yatırım Tavsiyesi/Yatırım Danışmanlığı" veya "Örnek Fon Mobil" ise "Bilgi Talebi";
konu belirsizse "Diğer".

### D-8 Yönetici ile görüşme talebi
Arayan yalnızca belirli bir yönetici ile görüşmek istiyorsa tür "Bilgi Talebi"dir,
şikayet değildir (şikayet dili yoksa).

## K — Bildirimin Konusu

### K-1 Fon Getirilerinin Düşüklüğü
En yüksek önceliklidir: zarar, kayıp, düşüş, performans düşüklüğü, getiri düşüklüğü,
fiyat düştü, değer kaybetti, eksi getiri, "param eridi".

### K-2 Yatırım Tavsiyesi/Yatırım Danışmanlığı
Müşteri tavsiye veya danışmanlık istiyorsa: "hangi fonu almalıyım", "paramı değerlendirmek
istiyorum", özel portföy yönetimi, özel fon kurma, fon kurulumu için alt limit sorusu.

### K-3 Örnek Fon Mobil
Örnek Fon Mobil uygulaması AÇIKÇA geçiyorsa. "Uygulama" kelimesi tek başına yetmez;
ÖrnekCep veya başka banka uygulamaları bu konuya girmez (onlar alım/satım veya banka konusudur).
Uygulama bağlamı yoksa bu konu seçilemez.

### K-4 İşlem sorunu + bilgi isteği (K-5'ten ÖNCE uygulanır)
Müşteri bir işlem sorunu yaşıyor (alım/satım emri gerçekleşmedi, limit/uyarı aldı, cüzdan, bakiye,
para çekme, havale, "geçmedi/yatmadı", emir beklemede) VE aynı zamanda bilgi istiyorsa (nedir,
nasıl, neden, ne zaman, şartlar neden değişti) konu "Fonlar ve Hizmetlerimiz Hakkında Bilgi"dir.
Sadece sorun bildiriyor, hiçbir bilgi istemiyorsa "Diğer".

### K-5 Alım/Satım Esasları/Operasyonel Süreç
Müşteri bir işlemi YAPMAK ya da işlem kuralını öğrenmek istiyorsa: alım/satım esasları, valör,
kesim saati, komisyon, fon bozdurma, fon transferi, emir iptali, saklama hesabı, devir işlemi,
"fonu nasıl alırım/satarım", "satış yapınca para ne zaman geçer".

### K-5b Dolandırıcılık ihbarı
Dolandırıcılık, sahte hesap/WhatsApp grubu, şirket adını kullanan sahte kişi ihbarlarında konu
"Fonlar ve Hizmetlerimiz Hakkında Bilgi"dir ("Diğer" DEĞİL). İş birimi bu bildirimlerin raporda
gözden kaçmamasını istemektedir; tür yine "Şikayet"tir (kural D-2).

### K-6 Fonlar ve Hizmetlerimiz Hakkında Bilgi (geniş varsayılan)
Fon bilgisi, fiyatı, içeriği, karşılaştırma, yönetim ücreti, stopaj, vergi, temettü/kar payı,
TEFAS, nitelikli yatırımcı, hesap açılışı, varlık dağılımı, belge/ekstre talebi, yönetici
ile görüşme talebi.

### K-7 Diğer
Hiçbiri eşleşmiyorsa "Diğer": hat kesildi, alakasız konu, anlaşılamayan içerik, başka
kurumun konusu.

## I — Muhatap Kurum

### I-1 Varsayılan Örnek Portföy
Konuşulan ürün/hizmet Örnek Portföy fonu, ücreti, uygulaması veya hizmetiyse ve başka bir
kurum açıkça işaret edilmiyorsa muhatap "Örnek Portföy"dür. Örnek Portföy'e devir/aktarım
talepleri ve fonlar hakkında bilgi istekleri de "Örnek Portföy"dür.

### I-2 Örnek Bank yalnızca açıkça geçerse
"Örnek Bank" SADECE görüşmede Örnek Bank, ÖrnekCep veya Örnek Bank şubesi AÇIKÇA geçiyorsa
ve konu banka kanalındaki işlemse seçilir. Örnek Bank işaretleri: ÖrnekCep, şube işlemleri,
banka hesabı, havale/EFT, bankadaki fon alım-satım ekranı. Müşteri fonu Örnek Bank kanalından
alıp satıyorsa ve sorusu/sorunu bu kanaldaki işlemle ilgiliyse (ekran hatası, paranın banka
hesabına geçişi, ÖrnekCep'te işlem) muhatap "Örnek Bank"tır. Banka adı hiç geçmiyorsa ve konu
Örnek Portföy fonuysa muhatap "Örnek Portföy"dür.

### I-3 Başka banka kanalı Diğer Kurumlar'dır
Müşteri fonu başka bir banka ya da aracı kurum üzerinden alıyorsa (Kuzey Bank, Liman Bankası,
Yıldız Katılım Bankası, Anka Bank vb.) ve sorun o kanaldaysa muhatap "Diğer Kurumlar"dır.
"Garanti" kelimesi Türkçede sık geçer ("garanti getiri"); kurum adı olarak geçmiyorsa
dikkate alma.

### I-4 Örnek Yatırım
Yalnızca konunun kendisi Örnek Yatırım ürünü/hizmetiyse seçilir: TraderPro platformu,
hisse/VİOP işlemleri, Örnek Yatırım hesap sorunları. Örnek Yatırım çalışanı müşterisi için
Örnek Portföy fonu soruyorsa muhatap "Örnek Portföy"dür.

### I-5 Piyasa altyapı kuruluşları
MKK, KAP, Takasbank, TEFAS gibi altyapı kuruluşlarıyla ilgili veri teyidi Örnek Portföy'ün
işidir; muhatap "Diğer Kurumlar" olamaz.

## J — Fon Kodu

### J-1 Yalnızca sözlükteki kodlar
Fon kodu yalnızca resmi fon sözlüğündeki kodlardan biri olabilir. Sözlükte olmayan harf dizisi
fon kodu değildir. Kod bulmak için fon_ara aracını kullan, emin olmadan kod yazma.

### J-2 Kod telaffuzu ve heceleme
Harf harf söylenen kodları birleştir ("o re te" → ORT, "o a le" → OAL). Müşteri kodu şehir
alfabesiyle heceleyebilir ("Ordu Ankara Lüleburgaz" = O-A-L); şehir adlarını fon adı sanma.

### J-3 Ö/O karışıklığı
Örnek Portföy kodlarının çoğu "O" ile başlar; konuşma tanıma sistemi bunu sık sık "Ö" yazar
(ÖRT, ÖAL, ÖP1). İlk harfi O yapınca sözlükte bir kod çıkıyorsa doğru kod odur.

### J-4 Ad eşleşmesi
Müşteri kod yerine fonun adını söyleyebilir ("altın fonu", "pilotfon temkinli"). Ad sözlükte
tek bir fona işaret ediyorsa o fonun kodunu yaz. Genel ad birden fazla fona uyuyorsa
niteleyicisiz temel fonu seç ("para piyasası fonu" → OP1, "ikinci para piyasası" → OP2,
"katılım para piyasası" → OPK). Genel addan seçim yaptıysan güveni 60-75 arası ver.

### J-5 Kod olmayan kısaltmalar
TL, USD, EUR, SPK, BIST, TEFAS, BES, OKS, ETF, KAP, MKK, IBAN gibi kısaltmalar fon kodu değildir.
"HER" gibi Türkçe kelimeyle çakışan kodlar yalnızca fon bağlamında ("HER fonu") kod sayılır.

### J-6 Kişi adlarından kod türetilmez — özel fon istisnası
Müşteri veya temsilci adı fon kodu değildir. İSTİSNA: özel fonlar sahibinin adını taşır.
Arayanın SOYADI sözlükteki bir "Özel Fon"un adıyla eşleşiyor ve müşteri kendi fonundan
bahsediyorsa o kodu yaz. Sadece ad (ör. "Barış") eşleşmesi yetmez; soyad gerekir.

### J-7 Başka şirketin fonu ve çoklu kod
Başka portföy şirketinin fonu (ör. Tepe Portföy) konuşuluyorsa kod yazma ("-").
Birden fazla Örnek Portföy fonu konuşulduysa kodları virgül ve boşlukla ayır: "ORT, OAL".
Fon ne ad ne kod olarak geçmiyorsa değer "-"dir.

## L — Bildirim Detayı

### L-1 Biçim
Tek paragraf, 4-7 cümle, Türkçe, üçüncü şahıs, akıcı resmi dil. Yönetim ve uyum ekibi okur.

### L-2 İlk cümle türün dayanağıdır
İlk cümle müşteriyi ve aramanın ASIL amacını vermeli, seçilen bildirim türünü görünür
kılmalıdır. Tür "Şikayet" ise ilk cümlede şikayet/memnuniyetsizlik açıkça geçmeli; "Öneri"
ise müşterinin öneri iletmek için aradığı yazmalı; "Hat Kesildi" ise görüşmenin içerik
üretmediği söylenmelidir.

### L-3 İçerik sırası
Transkriptte varsa sırasıyla: müşteri kim / kim adına arıyor; ne için aradı; hangi fon/ürün/
hizmet konuşuldu; temsilcinin verdiği yanıt veya yönlendirme; görüşmenin sonucu
(çözüldü / yönlendirildi / geri dönüş sözü / müşteri memnun-memnuniyetsiz ayrıldı).

### L-4 Uydurma yasak
Sadece transkriptte geçenleri yaz. Tarih, saat, tutar gibi değerleri yalnızca açıkça geçtiyse
yaz. Anlaşılamayan ürün adını aynen aktarma; "(ürün adı net anlaşılamadı)" yaz.

### L-5 Kişisel veri
Telefon, TC kimlik, IBAN asla açık yazılmaz; "[TELEFON]" gibi etiketleri de kopyalama,
doğal dille geç ("iletişim numarasını paylaştı").

### L-6 Kod ve ad tutarlılığı
Fon kodlarını resmi haliyle yaz. Fon adıyla birlikte parantez içinde kod yazacaksan ad ile kod
aynı fona ait olmalı. Başka şirketin fonuna Örnek Portföy kodu atfetme.

### L-7 Kanal kurumunun adını yaz
Müşteri işlemi bir banka veya aracı kurum üzerinden yapıyorsa o kurumun ADINI açıkça yaz
("Kuzey Bank üzerinden"). "İlgili banka" gibi adsız ifadeler yetersizdir, çünkü muhatap kurum
alanı bu ada göre belirlenir. Ad anlaşılamadıysa "(kurum adı kayıttan net anlaşılamadı)" yaz.

### L-8 Temsilciyi müşteri sanma
Çağrıyı karşılayan temsilci (Elif Aksoy, Burcu Tan, Selin Er, Kaan Yurt) müşteri değildir.
"Müşteri Selin Hanım" gibi temsilci adını müşteriye atfeden cümle yazma.

### L-9 Dolandırıcılık ve yönetici talebi
Dolandırıcılık veya sahte hesap ihbarı mutlaka belirtilir. Müşteri bir yönetici ile görüşme
talep ettiyse belirtilir.

## E — Bildirim Sahibi

### E-1 Arayanın adı
Arayan kendini tanıttıysa söylediği adı yaz (ad + soyad varsa ikisi birden). Temsilci
müşteriye adıyla hitap ediyorsa ("Ayşe Hanım") ve müşteri itiraz etmiyorsa o ad kullanılabilir.
Başkası adına arayan kişi kendini tanıttıysa ARAYANIN adı yazılır.

### E-2 Hitap sözcükleri ve boş değer
"Bey", "Hanım", "Sayın", "Müşteri" gibi hitapları değere koyma. Ad hiç söylenmediyse değer
boş bırakılır; ad uydurulmaz, maskeli ifadeler ad sanılmaz.

### E-3 Temsilci adları yasak
Temsilci adları (Elif Aksoy, Burcu Tan, Selin Er, Kaan Yurt ve yakın varyantları) bildirim
sahibi olamaz. Arayanın adı ayrıca söylenmediyse değer boştur.
