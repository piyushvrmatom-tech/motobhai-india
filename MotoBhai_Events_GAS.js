// ============================================================
// MotoBhai - Motorcycle Events India Fetcher
// Google Apps Script — Code.gs
// ============================================================
// SETUP STEPS:
//  1. Open Google Sheets → Extensions → Apps Script
//  2. Paste this entire file into Code.gs
//  3. Fill in the three constants below
//  4. Run setupTrigger() once from the Apps Script editor
// ============================================================

const SPREADSHEET_ID   = '1Mb__AP1TjBGMZgBrE_Kk7UiY0jc9RpBms6KgUr5kFjc';   // From your Sheet URL
const SERPAPI_KEY      = 'YOUR_SERPAPI_KEY_HERE';       // Free key at serpapi.com
const EVENTBRITE_TOKEN = 'YOUR_EVENTBRITE_TOKEN_HERE';  // Free at eventbrite.com/platform

const SHEET_NAME = 'MotoBhai Events';

const HEADERS = [
  'Timestamp Added',       // A
  'Event Name',            // B
  'Sponsor / Organizer',   // C
  'Event Date',            // D
  'Event Time',            // E
  'Venue',                 // F
  'City',                  // G
  'State',                 // H
  'Ticket Fee (INR)',       // I
  'Activities',            // J
  'More Details',          // K
  'Contact Number',        // L
  'Registration Email/Website', // M
  'Source URL',            // N
  'Status'                 // O  → Past / Today / Upcoming
];

// ============================================================
// SETUP — Run once to create headers + trigger
// ============================================================
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  fetchAllEvents();
  ScriptApp.newTrigger('fetchAllEvents').timeBased().everyHours(6).create();
  Logger.log('Trigger set. Events will auto-refresh every 6 hours.');
}

// ============================================================
// MASTER FETCH
// ============================================================
function fetchAllEvents() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    setupSheetHeaders(sheet);
  }
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, HEADERS.length).clearContent();

  const allEvents = [];
  allEvents.push(...fetchFromEventbrite());
  allEvents.push(...fetchFromSerpAPI());
  allEvents.push(...fetchRoyalEnfieldEvents());
  allEvents.push(...getKnownIndiaEvents());

  const deduplicated = deduplicateEvents(allEvents);
  const now = new Date();

  const rows = deduplicated.map(ev => {
    const evDate = ev.eventDate ? new Date(ev.eventDate) : null;
    let status = 'Upcoming';
    if (evDate) {
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const evDay  = new Date(evDate.getFullYear(), evDate.getMonth(), evDate.getDate());
      if (evDay < today) status = 'Past';
      else if (evDay.getTime() === today.getTime()) status = 'Today';
    }
    return [
      Utilities.formatDate(now, 'Asia/Kolkata', 'yyyy-MM-dd HH:mm:ss'),
      ev.name         || '',
      ev.sponsor      || '',
      ev.eventDate    || '',
      ev.eventTime    || '',
      ev.venue        || '',
      ev.city         || '',
      ev.state        || '',
      ev.ticketFee    || 'Free',
      ev.activities   || '',
      ev.moreDetails  || '',
      ev.contact      || '',
      ev.registration || '',
      ev.sourceUrl    || '',
      status
    ];
  });

  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, HEADERS.length).setValues(rows);
    applyConditionalFormatting(sheet, rows.length);
  }

  // Write metadata
  const meta = ss.getSheetByName('Meta') || ss.insertSheet('Meta');
  meta.getRange('A1').setValue('Last Updated');
  meta.getRange('B1').setValue(Utilities.formatDate(now, 'Asia/Kolkata', 'yyyy-MM-dd HH:mm:ss'));
  meta.getRange('A2').setValue('Total Events');
  meta.getRange('B2').setValue(rows.length);

  Logger.log('Fetched ' + rows.length + ' events.');
}

// ============================================================
// SOURCE 1 — Eventbrite API
// ============================================================
function fetchFromEventbrite() {
  const events = [];
  const keywords = ['motorcycle India', 'bike rally India', 'moto ride India', 'superbike India'];
  keywords.forEach(kw => {
    try {
      const url = 'https://www.eventbriteapi.com/v3/events/search/?q='
        + encodeURIComponent(kw)
        + '&location.address=India&expand=venue,organizer,ticket_availability&token='
        + EVENTBRITE_TOKEN;
      const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      if (resp.getResponseCode() !== 200) return;
      const data = JSON.parse(resp.getContentText());
      if (!data.events) return;
      data.events.forEach(ev => {
        const start = ev.start ? ev.start.local : '';
        const parts = start ? start.split('T') : ['', ''];
        const venue = ev.venue;
        events.push({
          name:         ev.name && ev.name.text ? ev.name.text : '',
          sponsor:      ev.organizer ? ev.organizer.name : '',
          eventDate:    parts[0] || '',
          eventTime:    parts[1] ? parts[1].substring(0, 5) : '',
          venue:        venue ? (venue.name + (venue.address && venue.address.address_1 ? ', ' + venue.address.address_1 : '')) : '',
          city:         venue && venue.address ? venue.address.city : '',
          state:        venue && venue.address ? venue.address.region : '',
          ticketFee:    ev.ticket_availability && ev.ticket_availability.minimum_ticket_price
                          ? ev.ticket_availability.minimum_ticket_price.display : 'Free',
          activities:   'Motorcycle Event',
          moreDetails:  ev.description && ev.description.text ? ev.description.text.substring(0, 300) : '',
          contact:      '',
          registration: ev.url || '',
          sourceUrl:    ev.url || ''
        });
      });
    } catch(e) { Logger.log('Eventbrite error: ' + e.message); }
  });
  return events;
}

// ============================================================
// SOURCE 2 — SerpAPI Google Events
// ============================================================
function fetchFromSerpAPI() {
  const events = [];
  const queries = [
    'motorcycle rally India 2026',
    'bike fest India 2026',
    'superbike meet India 2026',
    'Royal Enfield rides India 2026',
    'moto event India 2026'
  ];
  queries.forEach(q => {
    try {
      const url = 'https://serpapi.com/search.json?engine=google_events&q='
        + encodeURIComponent(q)
        + '&location=India&api_key=' + SERPAPI_KEY;
      const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      if (resp.getResponseCode() !== 200) return;
      const data = JSON.parse(resp.getContentText());
      if (!data.events_results) return;
      data.events_results.forEach(ev => {
        const dateInfo = ev.date || {};
        events.push({
          name:         ev.title || '',
          sponsor:      ev.venue ? ev.venue.name : '',
          eventDate:    dateInfo.start_date || '',
          eventTime:    dateInfo.when || '',
          venue:        ev.venue ? ev.venue.name : '',
          city:         ev.address ? ev.address[1] : '',
          state:        ev.address ? ev.address[2] : '',
          ticketFee:    ev.ticket_info ? ev.ticket_info.map(function(t){ return t.source; }).join(' | ') : 'Check website',
          activities:   ev.description ? ev.description.substring(0, 200) : '',
          moreDetails:  ev.description ? ev.description.substring(0, 400) : '',
          contact:      '',
          registration: ev.link || '',
          sourceUrl:    ev.link || ''
        });
      });
    } catch(e) { Logger.log('SerpAPI error: ' + e.message); }
  });
  return events;
}

// ============================================================
// SOURCE 3 — Royal Enfield India Rides Calendar
// ============================================================
function fetchRoyalEnfieldEvents() {
  const events = [];
  try {
    const url = 'https://www.royalenfield.com/in/en/rides-calendar/';
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return events;
    const html = resp.getContentText();
    const pattern = /<h[23][^>]*>([^<]{10,80})<\/h[23]>/gi;
    let match;
    while ((match = pattern.exec(html)) !== null) {
      const title = match[1].trim();
      if (/ride|odyssey|moto|rally|tour|fest/i.test(title)) {
        events.push({
          name:         title,
          sponsor:      'Royal Enfield India',
          eventDate:    '',
          eventTime:    '',
          venue:        'India (varies)',
          city:         '',
          state:        '',
          ticketFee:    'Contact RE dealer',
          activities:   'Group Ride, Motorcycle Tour',
          moreDetails:  'Royal Enfield organized group ride. Register via RE dealership or website.',
          contact:      '1800-210-0007',
          registration: 'https://www.royalenfield.com/in/en/rides-calendar/',
          sourceUrl:    url
        });
      }
    }
  } catch(e) { Logger.log('RE fetch error: ' + e.message); }
  return events;
}

// ============================================================
// SOURCE 4 — Known Annual India Motorcycle Events (seeded data)
// ============================================================
function getKnownIndiaEvents() {
  return [
    {
      name:         'India Bike Week (IBW) 2026',
      sponsor:      'India Bike Week Productions',
      eventDate:    '2026-11-28',
      eventTime:    '10:00',
      venue:        'Vagator Beach, Goa',
      city:         'Vagator',
      state:        'Goa',
      ticketFee:    '₹2999 – ₹9999',
      activities:   'Stunt Shows, Live Music, Custom Bike Display, Trade Stalls, Drag Race, Group Rides',
      moreDetails:  "India's biggest motorcycle festival at Goa. International stunts, music, custom builds, bike expos and coastal group rides. 3-day pass available.",
      contact:      '+91-9820098200',
      registration: 'https://www.indiabike.in',
      sourceUrl:    'https://www.indiabike.in'
    },
    {
      name:         'Himalayan Odyssey 2026',
      sponsor:      'Royal Enfield India',
      eventDate:    '2026-07-05',
      eventTime:    '06:00',
      venue:        'Manali, Himachal Pradesh',
      city:         'Manali',
      state:        'Himachal Pradesh',
      ticketFee:    '₹35,000 (all inclusive)',
      activities:   'High Altitude Ride, Leh Ladakh Passes, Camping, Camaraderie',
      moreDetails:  '2-week high altitude motorcycle expedition from Manali to Leh crossing Rohtang La, Baralacha La, Tanglang La. For Royal Enfield riders.',
      contact:      '1800-210-0007',
      registration: 'https://www.royalenfield.com/in/en/rides-calendar/',
      sourceUrl:    'https://www.royalenfield.com/in/en/rides-calendar/'
    },
    {
      name:         'Rajasthan Desert Storm 2026',
      sponsor:      'Team Desert Storm',
      eventDate:    '2026-02-15',
      eventTime:    '07:00',
      venue:        'Jaisalmer, Rajasthan',
      city:         'Jaisalmer',
      state:        'Rajasthan',
      ticketFee:    '₹5,000 (includes stay)',
      activities:   'Desert Off-road, Sand Dune Ride, Campfire, Camel Safari',
      moreDetails:  'Annual motorcycle adventure across Rajasthan sand dunes. Iconic Indian desert ride.',
      contact:      '+91-9876543210',
      registration: 'https://www.royalenfield.com/in/en/rides-calendar/',
      sourceUrl:    'https://www.royalenfield.com/in/en/rides-calendar/'
    },
    {
      name:         'Bengaluru Bikers Conclave 2026',
      sponsor:      'Bikers of Bangalore',
      eventDate:    '2026-08-20',
      eventTime:    '09:00',
      venue:        'Kanteerava Stadium, Bengaluru',
      city:         'Bengaluru',
      state:        'Karnataka',
      ticketFee:    '₹499',
      activities:   'Superbike Show, Stunt Display, Drag Racing, Custom Build Contest',
      moreDetails:  "South India's premier biking conclave with superbike displays, stunt shows and drag racing.",
      contact:      '+91-8880001234',
      registration: 'https://bb-conclave.in',
      sourceUrl:    'https://bb-conclave.in'
    },
    {
      name:         'MotoBhai Delhi NCR Community Ride',
      sponsor:      'MotoBhai',
      eventDate:    '2026-10-05',
      eventTime:    '07:00',
      venue:        'India Gate, New Delhi',
      city:         'New Delhi',
      state:        'Delhi',
      ticketFee:    'Free',
      activities:   'Group Ride, Breakfast Meet, Photo Session, Route Navigation',
      moreDetails:  'MotoBhai community group ride from India Gate via Dwarka Expressway to Manesar. All bikes welcome.',
      contact:      '+91-9999999999',
      registration: 'https://motobhai.in/events',
      sourceUrl:    'https://motobhai.in'
    }
  ];
}

// ============================================================
// UTILITIES
// ============================================================
function deduplicateEvents(events) {
  const seen = new Set();
  return events.filter(ev => {
    const key = (ev.name + '|' + ev.eventDate).toLowerCase().trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function setupSheetHeaders(sheet) {
  const hRange = sheet.getRange(1, 1, 1, HEADERS.length);
  hRange.setValues([HEADERS]);
  hRange.setBackground('#1a1a2e');
  hRange.setFontColor('#e94560');
  hRange.setFontWeight('bold');
  hRange.setFontSize(11);
  sheet.setFrozenRows(1);
  [160,250,180,110,90,200,120,120,130,250,300,140,220,200,90].forEach((w,i) => sheet.setColumnWidth(i+1, w));
}

function applyConditionalFormatting(sheet, dataRows) {
  for (let row = 2; row <= dataRows + 1; row++) {
    const status = sheet.getRange(row, 15).getValue();
    const rowRange = sheet.getRange(row, 1, 1, HEADERS.length);
    if (status === 'Today')       rowRange.setBackground('#fff3cd');
    else if (status === 'Past')   { rowRange.setFontColor('#888888'); rowRange.setBackground('#f8f9fa'); }
    else                          rowRange.setBackground('#d4edda');
  }
}

// ============================================================
// WEB APP API — Deploy as "Anyone can access" Web App
// Called by MotoBhai iOS app via URLSession
// GET ?filter=all | past | today | upcoming
// ============================================================
function doGet(e) {
  const filter = e.parameter.filter || 'all';
  const ss     = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet  = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    return ContentService
      .createTextOutput(JSON.stringify({ error: 'Sheet not found' }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  const data    = sheet.getDataRange().getValues();
  const headers = data[0];
  const rows    = data.slice(1);

  const events = rows
    .filter(row => row[0] !== '')
    .filter(row => filter === 'all' || (row[14] || '').toString().toLowerCase() === filter.toLowerCase())
    .map(row => {
      const obj = {};
      headers.forEach((h, i) => {
        const key = h.toString()
          .replace(/[^a-zA-Z0-9 ]/g, '')
          .split(' ')
          .map((w, idx) => idx === 0 ? w.toLowerCase() : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
          .join('');
        obj[key] = row[i] !== undefined && row[i] !== null ? row[i].toString() : '';
      });
      return obj;
    });

  const output = {
    lastUpdated: new Date().toISOString(),
    filter:      filter,
    totalEvents: events.length,
    events:      events
  };

  return ContentService
    .createTextOutput(JSON.stringify(output))
    .setMimeType(ContentService.MimeType.JSON);
}

function testFetch() {
  fetchAllEvents();
  Logger.log('Test complete. Check the sheet.');
}
