// MotoBhai India — Events Calendar  |  Google Apps Script (Code.gs)
// ────────────────────────────────────────────────────────────────────
// Sheet structure expected in the "Events" tab:
// Col A: Title       Col B: Type (ride/meetup/rally/training/expo)
// Col C: Date        Col D: Time       Col E: Location
// Col F: City        Col G: State      Col H: Description
// Col I: Organizer   Col J: Fee        Col K: Link
// Col L: Status (Active / Inactive)
// ────────────────────────────────────────────────────────────────────

const SPREADSHEET_ID   = '1Mb__AP1TjBGMZgBrE_Kk7UiY0jc9RpBms6KgUr5kFjc';
const EVENTS_SHEET     = 'Events';
const HEADER_ROW       = 1;          // Row 1 is the header

// ── Entry point ──────────────────────────────────────────────────────
function doGet(e) {
  const action = (e && e.parameter && e.parameter.action) || 'getEvents';
  let result;

  try {
    switch (action) {
      case 'getEvents': result = getEvents(e);  break;
      case 'ping':      result = { status: 'ok', timestamp: new Date().toISOString() }; break;
      default:          result = { error: 'Unknown action: ' + action };
    }
  } catch (err) {
    result = { error: err.message };
  }

  return ContentService
    .createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── getEvents ────────────────────────────────────────────────────────
function getEvents(e) {
  const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(EVENTS_SHEET);

  if (!sheet) {
    return { events: [], warning: 'Sheet "' + EVENTS_SHEET + '" not found. Create it with the expected columns.' };
  }

  const lastRow = sheet.getLastRow();
  if (lastRow <= HEADER_ROW) {
    return { events: [], info: 'No event rows found.' };
  }

  const numRows = lastRow - HEADER_ROW;
  const data    = sheet.getRange(HEADER_ROW + 1, 1, numRows, 12).getValues();

  // Optional filters from query params
  const filterType  = (e && e.parameter && e.parameter.type)  ? e.parameter.type.toLowerCase()  : null;
  const filterCity  = (e && e.parameter && e.parameter.city)  ? e.parameter.city.toLowerCase()  : null;
  const filterState = (e && e.parameter && e.parameter.state) ? e.parameter.state.toLowerCase() : null;

  const events = [];
  const now    = new Date(); now.setHours(0, 0, 0, 0);

  data.forEach(function(row) {
    const status = (row[11] || '').toString().trim().toLowerCase();
    if (status === 'inactive') return;                    // Skip inactive rows

    const dateVal = row[2];
    let parsedDate;
    try { parsedDate = new Date(dateVal); } catch(_) { parsedDate = null; }

    // Only return upcoming events (including today)
    if (parsedDate && !isNaN(parsedDate.getTime())) {
      const d = new Date(parsedDate); d.setHours(0, 0, 0, 0);
      if (d < now) return;                                // Past event → skip
    }

    const ev = {
      title:       safeStr(row[0]),
      type:        safeStr(row[1]),
      date:        formatDate_(dateVal),
      time:        safeStr(row[3]),
      location:    safeStr(row[4]),
      city:        safeStr(row[5]),
      state:       safeStr(row[6]),
      description: safeStr(row[7]),
      organizer:   safeStr(row[8]),
      fee:         safeStr(row[9]),
      link:        safeStr(row[10]),
      status:      safeStr(row[11]) || 'Active'
    };

    if (!ev.title) return;                               // Skip empty rows

    // Apply optional type / city / state filters
    if (filterType  && ev.type.toLowerCase()  !== filterType)  return;
    if (filterCity  && ev.city.toLowerCase()  !== filterCity)  return;
    if (filterState && ev.state.toLowerCase() !== filterState) return;

    events.push(ev);
  });

  // Sort by date ascending
  events.sort(function(a, b) {
    return new Date(a.date) - new Date(b.date);
  });

  return {
    events:    events,
    total:     events.length,
    fetched_at: new Date().toISOString(),
    sheet:     EVENTS_SHEET,
    spreadsheet_id: SPREADSHEET_ID
  };
}

// ── Helpers ──────────────────────────────────────────────────────────
function safeStr(val) {
  if (val === null || val === undefined) return '';
  return val.toString().trim();
}

function formatDate_(raw) {
  if (!raw) return '';
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw.toString().trim();
  return Utilities.formatDate(d, 'Asia/Kolkata', 'dd MMM yyyy');
}

// ── Quick local test (run from Apps Script editor) ───────────────────
function testGetEvents() {
  const result = getEvents({ parameter: {} });
  Logger.log(JSON.stringify(result, null, 2));
}
