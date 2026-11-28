export const UNKNOWN_LANGUAGE = "unknown";
export const MAX_ACTIVE_RESUMES_LIMIT = 5;

/**
 * Full canonical ISO 639-1 2-letter language registry (184 codes) with complete English display names.
 * Bundling all 184 names avoids trimmed-ICU browser gaps (e.g. Chrome returning "aa"/"ab"/"ae"
 * or mapping "tw" to duplicate "Akan" via Intl.DisplayNames).
 */
const ISO_639_1_NAMES: Readonly<Record<string, string>> = {
    aa: "Afar",
    ab: "Abkhazian",
    ae: "Avestan",
    af: "Afrikaans",
    ak: "Akan",
    am: "Amharic",
    an: "Aragonese",
    ar: "Arabic",
    as: "Assamese",
    av: "Avaric",
    ay: "Aymara",
    az: "Azerbaijani",
    ba: "Bashkir",
    be: "Belarusian",
    bg: "Bulgarian",
    bh: "Bihari",
    bi: "Bislama",
    bm: "Bambara",
    bn: "Bangla",
    bo: "Tibetan",
    br: "Breton",
    bs: "Bosnian",
    ca: "Catalan",
    ce: "Chechen",
    ch: "Chamorro",
    co: "Corsican",
    cr: "Cree",
    cs: "Czech",
    cu: "Church Slavic",
    cv: "Chuvash",
    cy: "Welsh",
    da: "Danish",
    de: "German",
    dv: "Divehi",
    dz: "Dzongkha",
    ee: "Ewe",
    el: "Greek",
    en: "English",
    eo: "Esperanto",
    es: "Spanish",
    et: "Estonian",
    eu: "Basque",
    fa: "Persian",
    ff: "Fula",
    fi: "Finnish",
    fj: "Fijian",
    fo: "Faroese",
    fr: "French",
    fy: "Western Frisian",
    ga: "Irish",
    gd: "Scottish Gaelic",
    gl: "Galician",
    gn: "Guarani",
    gu: "Gujarati",
    gv: "Manx",
    ha: "Hausa",
    he: "Hebrew",
    hi: "Hindi",
    ho: "Hiri Motu",
    hr: "Croatian",
    ht: "Haitian Creole",
    hu: "Hungarian",
    hy: "Armenian",
    hz: "Herero",
    ia: "Interlingua",
    id: "Indonesian",
    ie: "Interlingue",
    ig: "Igbo",
    ii: "Sichuan Yi",
    ik: "Inupiaq",
    io: "Ido",
    is: "Icelandic",
    it: "Italian",
    iu: "Inuktitut",
    ja: "Japanese",
    jv: "Javanese",
    ka: "Georgian",
    kg: "Kongo",
    ki: "Kikuyu",
    kj: "Kuanyama",
    kk: "Kazakh",
    kl: "Kalaallisut",
    km: "Khmer",
    kn: "Kannada",
    ko: "Korean",
    kr: "Kanuri",
    ks: "Kashmiri",
    ku: "Kurdish",
    kv: "Komi",
    kw: "Cornish",
    ky: "Kyrgyz",
    la: "Latin",
    lb: "Luxembourgish",
    lg: "Ganda",
    li: "Limburgish",
    ln: "Lingala",
    lo: "Lao",
    lt: "Lithuanian",
    lu: "Luba-Katanga",
    lv: "Latvian",
    mg: "Malagasy",
    mh: "Marshallese",
    mi: "Māori",
    mk: "Macedonian",
    ml: "Malayalam",
    mn: "Mongolian",
    mr: "Marathi",
    ms: "Malay",
    mt: "Maltese",
    my: "Burmese",
    na: "Nauru",
    nb: "Norwegian Bokmål",
    nd: "North Ndebele",
    ne: "Nepali",
    ng: "Ndonga",
    nl: "Dutch",
    nn: "Norwegian Nynorsk",
    no: "Norwegian",
    nr: "South Ndebele",
    nv: "Navajo",
    ny: "Nyanja",
    oc: "Occitan",
    oj: "Ojibwa",
    om: "Oromo",
    or: "Odia",
    os: "Ossetic",
    pa: "Punjabi",
    pi: "Pali",
    pl: "Polish",
    ps: "Pashto",
    pt: "Portuguese",
    qu: "Quechua",
    rm: "Romansh",
    rn: "Rundi",
    ro: "Romanian",
    ru: "Russian",
    rw: "Kinyarwanda",
    sa: "Sanskrit",
    sc: "Sardinian",
    sd: "Sindhi",
    se: "Northern Sami",
    sg: "Sango",
    si: "Sinhala",
    sk: "Slovak",
    sl: "Slovenian",
    sm: "Samoan",
    sn: "Shona",
    so: "Somali",
    sq: "Albanian",
    sr: "Serbian",
    ss: "Swati",
    st: "Southern Sotho",
    su: "Sundanese",
    sv: "Swedish",
    sw: "Swahili",
    ta: "Tamil",
    te: "Telugu",
    tg: "Tajik",
    th: "Thai",
    ti: "Tigrinya",
    tk: "Turkmen",
    tl: "Filipino",
    tn: "Tswana",
    to: "Tongan",
    tr: "Turkish",
    ts: "Tsonga",
    tt: "Tatar",
    tw: "Twi",
    ty: "Tahitian",
    ug: "Uyghur",
    uk: "Ukrainian",
    ur: "Urdu",
    uz: "Uzbek",
    ve: "Venda",
    vi: "Vietnamese",
    vo: "Volapük",
    wa: "Walloon",
    wo: "Wolof",
    xh: "Xhosa",
    yi: "Yiddish",
    yo: "Yoruba",
    za: "Zhuang",
    zh: "Chinese",
    zu: "Zulu",
};

export const ISO_639_1_CODES: readonly string[] = Object.keys(ISO_639_1_NAMES);

const ISO_639_1_SET = new Set<string>(ISO_639_1_CODES);

export interface LanguageOption {
    code: string;
    name: string;
    pinned?: boolean;
}

export function normalizeIsoLanguage(raw: string | null | undefined): string {
    const cleaned = (raw ?? "").trim().toLowerCase();
    if (!cleaned || cleaned === UNKNOWN_LANGUAGE) {
        return UNKNOWN_LANGUAGE;
    }
    const primary = cleaned.split(/[-_]/)[0] ?? "";
    return ISO_639_1_SET.has(primary) ? primary : UNKNOWN_LANGUAGE;
}

export function getLanguageName(code: string | null | undefined): string {
    const normalized = normalizeIsoLanguage(code);
    if (normalized === UNKNOWN_LANGUAGE) {
        return "Unknown";
    }
    return ISO_639_1_NAMES[normalized] ?? normalized.toUpperCase();
}

export function formatLanguageBadge(code: string | null | undefined): string {
    const normalized = normalizeIsoLanguage(code);
    if (normalized === UNKNOWN_LANGUAGE) {
        return "UNK";
    }
    return normalized.toUpperCase();
}

export function formatKnownLanguageBadge(code: string | null | undefined): string | null {
    const normalized = normalizeIsoLanguage(code);
    return normalized === UNKNOWN_LANGUAGE ? null : normalized.toUpperCase();
}

export function formatLanguageLabel(code: string | null | undefined): string {
    const normalized = normalizeIsoLanguage(code);
    if (normalized === UNKNOWN_LANGUAGE) {
        return "Unknown";
    }
    return `${getLanguageName(normalized)} (${normalized.toUpperCase()})`;
}

export function languageBadgeStyle(code: string | null | undefined): string {
    const normalized = normalizeIsoLanguage(code);
    if (normalized === UNKNOWN_LANGUAGE) {
        return "bg-zinc-900/70 text-zinc-500 ring-1 ring-zinc-800";
    }
    return "bg-sky-500/10 text-sky-300 ring-1 ring-sky-500/25";
}

export function getLanguageOptions(pinnedCodes: ReadonlyArray<string> = []): LanguageOption[] {
    const pinnedSet = new Set<string>();
    const pinnedOrdered: LanguageOption[] = [];

    for (const raw of pinnedCodes) {
        const code = normalizeIsoLanguage(raw);
        if (code !== UNKNOWN_LANGUAGE && !pinnedSet.has(code)) {
            pinnedSet.add(code);
            pinnedOrdered.push({ code, name: getLanguageName(code), pinned: true });
        }
    }

    const remaining: LanguageOption[] = ISO_639_1_CODES.filter((code) => !pinnedSet.has(code))
        .map((code) => ({
            code,
            name: getLanguageName(code),
            pinned: false,
        }))
        .sort((a, b) => a.name.localeCompare(b.name));

    return [...pinnedOrdered, ...remaining];
}

export function filterLanguageOptions(
    options: ReadonlyArray<LanguageOption>,
    query: string,
): LanguageOption[] {
    const q = query.trim().toLowerCase();
    if (!q) {
        return [...options];
    }
    return options.filter(
        (opt) => opt.code.toLowerCase().includes(q) || opt.name.toLowerCase().includes(q),
    );
}
