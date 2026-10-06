"""All user-visible strings (Greek).

UI code and error messages must take their text from here, never from inline literals.
To add another language later, turn these constants into a per-language table.
"""

# --- Window / general -------------------------------------------------------------------
WINDOW_TITLE = "VidGrab"
URL_PLACEHOLDER = "Επικόλλησε σύνδεσμο από YouTube, X, Facebook ή Instagram…"
BTN_PASTE = "Επικόλληση"
BTN_FETCH = "Ανάλυση"
BTN_DOWNLOAD = "Λήψη"
BTN_BROWSE = "Αλλαγή…"
BTN_OPEN_FOLDER = "Άνοιγμα φακέλου"
BTN_OPEN_LOGS = "Αρχείο καταγραφής"
BTN_SETTINGS = "Ρυθμίσεις"
BTN_CANCEL = "Ακύρωση"
BTN_RETRY = "Επανάληψη"
BTN_REMOVE = "Αφαίρεση"
BTN_CLEAR_FINISHED = "Καθαρισμός ολοκληρωμένων"
BTN_DETAILS = "Λεπτομέρειες"

LABEL_QUALITY = "Ποιότητα:"
LABEL_DESTINATION = "Φάκελος:"
LABEL_QUEUE = "Ουρά λήψεων"
LABEL_COOKIES = "Cookies για σύνδεση:"
LABEL_COOKIE_FILE = "Αρχείο cookies.txt:"
LABEL_MAX_CONCURRENT = "Ταυτόχρονες λήψεις:"
LABEL_DURATION = "Διάρκεια: {duration}"
LABEL_UPLOADER = "Από: {uploader}"
LABEL_FETCHING = "Ανάκτηση πληροφοριών…"
LABEL_NO_PREVIEW = "Επικόλλησε έναν σύνδεσμο και πάτησε «Ανάλυση»."

DIALOG_CHOOSE_FOLDER = "Επιλογή φακέλου προορισμού"
DIALOG_CHOOSE_COOKIE_FILE = "Επιλογή αρχείου cookies.txt"
DIALOG_COOKIE_FILE_FILTER = "Αρχεία cookies (*.txt);;Όλα τα αρχεία (*)"
DIALOG_SETTINGS_TITLE = "Ρυθμίσεις"
DIALOG_ERROR_TITLE = "Σφάλμα"
DIALOG_WARNING_TITLE = "Προειδοποίηση"
COOKIES_HINT = (
    "Χρειάζεται μόνο για περιεχόμενο που απαιτεί σύνδεση (π.χ. Instagram, Facebook). "
    "Προτείνεται ο Firefox."
)

CONFIRM_EXIT_TITLE = "Έξοδος"
CONFIRM_EXIT_TEXT = "Υπάρχουν λήψεις σε εξέλιξη. Να ακυρωθούν και να κλείσει η εφαρμογή;"
DOWNLOAD_ADDED = "Προστέθηκε στην ουρά: {title}"
OPEN_FILE_FAILED = "Δεν ήταν δυνατό το άνοιγμα: {path}"

# --- Quality ----------------------------------------------------------------------------
QUALITY_BEST = "Καλύτερη διαθέσιμη"
QUALITY_1080P = "1080p"
QUALITY_720P = "720p"
QUALITY_AUDIO = "Μόνο ήχος"

# --- Output format ----------------------------------------------------------------------
LABEL_FORMAT = "Μορφή:"
LABEL_BITRATE = "Bitrate:"
FORMAT_MP4 = "MP4"
FORMAT_MKV = "MKV"
AUDIO_FORMAT_MP3 = "MP3"
AUDIO_FORMAT_ORIGINAL = "Αρχικό (m4a/opus)"
BITRATE_ITEM = "{kbps} kbps"
TOOLTIP_FORMAT_VIDEO = (
    "MP4: παίζει παντού. Αν ο ήχος δεν είναι συμβατός, μετατρέπεται μόνο ο ήχος σε AAC· "
    "η εικόνα δεν επανακωδικοποιείται ποτέ.\n"
    "MKV: οι αρχικές ροές εικόνας και ήχου, χωρίς καμία μετατροπή."
)
TOOLTIP_FORMAT_AUDIO = (
    "MP3: μετατροπή σε MP3 στο bitrate που επιλέγεις.\n"
    "Αρχικό: ο ήχος όπως τον δίνει ο ιστότοπος (συνήθως m4a ή opus), χωρίς μετατροπή."
)
TOOLTIP_BITRATE = (
    "Η πηγή του YouTube είναι περίπου 128–160 kbps, οπότε τα 256 ή 320 kbps "
    "δεν βελτιώνουν την ποιότητα· απλώς μεγαλώνουν το αρχείο."
)
JOB_FORMAT = "{quality} · {format}"

# --- Cookie sources ---------------------------------------------------------------------
COOKIES_NONE = "Κανένα"
COOKIES_FIREFOX = "Firefox (προτείνεται)"
COOKIES_CHROME = "Chrome"
COOKIES_EDGE = "Edge"
COOKIES_FILE = "Αρχείο cookies.txt"

# --- Job status -------------------------------------------------------------------------
STATUS_QUEUED = "Σε αναμονή"
STATUS_DOWNLOADING = "Λήψη…"
STATUS_POSTPROCESSING = "Επεξεργασία (FFmpeg)…"
STATUS_CANCELLING = "Ακύρωση…"
STATUS_COMPLETED = "Ολοκληρώθηκε"
STATUS_FAILED = "Απέτυχε"
STATUS_CANCELLED = "Ακυρώθηκε"
PROGRESS_DETAIL = "{percent} · {speed} · απομένει {eta}"
PROGRESS_STREAM = "Ροή {index}/{count}"
STATUS_WITH_MESSAGE = "{status}: {message}"
UNKNOWN_VALUE = "—"

# --- Warnings ---------------------------------------------------------------------------
WARN_DENO_MISSING = (
    "Δεν βρέθηκε το Deno (JavaScript runtime). "
    "Οι λήψεις από YouTube μπορεί να έχουν περιορισμένη ποιότητα ή να αποτύχουν."
)
WARN_FFMPEG_MISSING = (
    "Δεν βρέθηκε το FFmpeg. Η συγχώνευση βίντεο/ήχου και η μετατροπή σε MP3 δεν θα λειτουργούν."
)

# --- Error messages ---------------------------------------------------------------------
ERR_INVALID_URL = "Ο σύνδεσμος δεν είναι έγκυρος. Επικόλλησε έναν πλήρη σύνδεσμο (https://…)."
ERR_UNSUPPORTED_URL = "Αυτός ο ιστότοπος ή ο σύνδεσμος δεν υποστηρίζεται."
ERR_PLAYLIST_NOT_SUPPORTED = "Οι λίστες αναπαραγωγής δεν υποστηρίζονται ακόμα. Επικόλλησε τον σύνδεσμο ενός μεμονωμένου βίντεο."
ERR_PRIVATE = "Το βίντεο είναι ιδιωτικό ή ο λογαριασμός είναι κλειδωμένος."
ERR_GEO_BLOCKED = "Το βίντεο δεν είναι διαθέσιμο στη χώρα σου (γεωγραφικός περιορισμός)."
ERR_LOGIN_REQUIRED = (
    "Απαιτείται σύνδεση. Συνδέσου στον ιστότοπο από τον browser σου και ενεργοποίησε "
    "τα cookies στις Ρυθμίσεις (προτείνεται ο Firefox)."
)
ERR_AGE_RESTRICTED = (
    "Το βίντεο έχει περιορισμό ηλικίας. Συνδέσου στον browser σου και ενεργοποίησε "
    "τα cookies στις Ρυθμίσεις."
)
ERR_UNAVAILABLE = "Το βίντεο δεν είναι διαθέσιμο (μπορεί να έχει διαγραφεί)."
ERR_FORMAT_UNAVAILABLE = (
    "Η ποιότητα που επέλεξες δεν είναι διαθέσιμη για αυτό το βίντεο. Δοκίμασε άλλη."
)
ERR_NETWORK = "Πρόβλημα σύνδεσης δικτύου. Έλεγξε το internet και δοκίμασε ξανά."
ERR_FFMPEG_MISSING = "Δεν βρέθηκε το FFmpeg, που χρειάζεται για αυτή τη λήψη."
ERR_COOKIES_FAILED = (
    "Δεν ήταν δυνατή η ανάγνωση των cookies από τον browser. Προτείνεται να επιλέξεις "
    "Firefox στις Ρυθμίσεις. Για Chrome/Edge, κλείσε εντελώς τον browser και δοκίμασε ξανά, "
    "ή χρησιμοποίησε αρχείο cookies.txt."
)
ERR_COOKIE_FILE_MISSING = "Το αρχείο cookies.txt δεν βρέθηκε: {path}"
ERR_DISK = "Σφάλμα εγγραφής αρχείου. Έλεγξε τον φάκελο προορισμού και τον ελεύθερο χώρο."
ERR_CANCELLED = "Η λήψη ακυρώθηκε."
ERR_UNKNOWN = "Κάτι πήγε στραβά. Δες το αρχείο καταγραφής για λεπτομέρειες."

# --- Self-check (console output, kept here for consistency) -----------------------------
SELF_CHECK_FOUND = "OK       {name}: {path}"
SELF_CHECK_MISSING = "MISSING  {name}"
