import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import mysql from 'mysql2/promise';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import crypto from 'crypto';

dotenv.config();
const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);
const app        = express();
const PORT       = process.env.PORT || 3001;

app.use(cors());
app.use(express.json({ limit: '10mb' }));

/* ── AUTH ─────────────────────────────────────────────── */
const JWT_SECRET   = process.env.JWT_SECRET || crypto.randomBytes(32).toString('hex');
const TOKEN_EXPIRY = 7 * 24 * 60 * 60 * 1000;

function hashPassword(password, salt) {
  if (!salt) salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(password, salt, 64).toString('hex');
  return { hash, salt };
}
function verifyPassword(password, hash, salt) {
  const { hash: check } = hashPassword(password, salt);
  return crypto.timingSafeEqual(Buffer.from(hash, 'hex'), Buffer.from(check, 'hex'));
}
function signToken(payload) {
  const data = { ...payload, exp: Date.now() + TOKEN_EXPIRY };
  const b64  = Buffer.from(JSON.stringify(data)).toString('base64url');
  const sig  = crypto.createHmac('sha256', JWT_SECRET).update(b64).digest('base64url');
  return b64 + '.' + sig;
}
function verifyToken(token) {
  if (!token) return null;
  const [b64, sig] = token.split('.');
  if (!b64 || !sig) return null;
  const expected = crypto.createHmac('sha256', JWT_SECRET).update(b64).digest('base64url');
  if (sig !== expected) return null;
  try {
    const data = JSON.parse(Buffer.from(b64, 'base64url').toString());
    if (data.exp && data.exp < Date.now()) return null;
    return data;
  } catch { return null; }
}

/* ── DB POOL ──────────────────────────────────────────── */
let pool = null;
try {
  pool = mysql.createPool({
    host:               process.env.DB_HOST || 'localhost',
    port:               parseInt(process.env.DB_PORT) || 3306,
    user:               process.env.DB_USER || 'root',
    password:           process.env.DB_PASSWORD || '',
    database:           process.env.DB_NAME || 'flw_shopify',
    waitForConnections: true,
    connectionLimit:    20,
    dateStrings:        true,
    queueLimit:         50,
    connectTimeout:     10000,
    ssl: process.env.DB_SSL === 'true' ? { rejectUnauthorized: false } : undefined,
  });
  console.log('MySQL pool created');
} catch (e) { console.warn('MySQL pool failed:', e.message); }

/* ── CACHE (2 min TTL) ────────────────────────────────── */
const _cache = new Map();
const TTL    = 2 * 60 * 1000;
function cKey(sql, p) { return sql.replace(/\s+/g, ' ').trim() + '|' + JSON.stringify(p); }
function cGet(k) { const e = _cache.get(k); if (!e) return null; if (Date.now()-e.ts > TTL) { _cache.delete(k); return null; } return e.v; }
function cSet(k, v) { if (_cache.size > 500) _cache.delete(_cache.keys().next().value); _cache.set(k, { v, ts: Date.now() }); }

/*
  Use pool.query() NOT pool.execute() — execute() uses prepared statements
  which fail with "Incorrect arguments to mysqld_stmt_execute" on derived tables / subqueries.
*/
async function q(sql, params = [], ms = 30000) {
  if (!pool) throw new Error('Database not connected');
  return Promise.race([
    pool.query(sql, params).then(([rows]) => rows),
    new Promise((_, rej) => setTimeout(() => rej(new Error('Query timed out after ' + ms + 'ms')), ms)),
  ]);
}
async function qc(sql, params = []) {
  const k = cKey(sql, params);
  const h = cGet(k);
  if (h) return h;
  const r = await q(sql, params);
  if (sql.trimStart().toUpperCase().startsWith('SELECT')) cSet(k, r);
  return r;
}

/* ── MIDDLEWARE ───────────────────────────────────────── */
// AUTH TEMPORARILY DISABLED
function auth(req, res, next) {
  req.user = { id: 1, email: 'admin@flw.com', name: 'Admin', role: 'admin' };
  next();
}
function adminOnly(req, res, next) {
  if (req.user.role !== 'admin') return res.status(403).json({ error: 'Forbidden' });
  next();
}

/* ── HELPERS ──────────────────────────────────────────── */
function dateRange(start, end) {
  const today = new Date().toISOString().slice(0, 10);
  if (!start) { const d = new Date(today); d.setDate(d.getDate()-29); start = d.toISOString().slice(0,10); }
  return [start, end || today];
}

// Returns index-friendly datetime params: [startDatetime, endDatetime]
// Usage: col >= ? AND col < DATE_ADD(?, INTERVAL 1 DAY)  →  [s, e]
// Or use sdP/edP directly for BETWEEN
function sdP(d) { return d + ' 00:00:00'; }
function edP(d) { return d + ' 23:59:59'; }

function wf(websiteId, alias = '') {
  const wid = websiteId && websiteId !== 'all' && websiteId !== '0' ? parseInt(websiteId) : null;
  const p   = alias ? `${alias}.` : '';
  return wid ? { sql: ` AND ${p}website_id = ?`, params: [wid] } : { sql: '', params: [] };
}

/*
  PROFIT FORMULA (from OrderService.dailyReportCompare source):
    profit = total_sale - total_cog - total_tax - payment_fee - total_ads - total_refunds
    total_sale shown to user = total_sale - tip  (tip deducted for display)
    margin = profit / (total_sale - tip) * 100
    aov    = (total_sale - tip) / total_order
    roas   = (total_sale - tip) / total_ads

  ORDER STATUS EXCLUDED in line item aggregation:
    whereNotIn('orders.status', ['failed', 'cancelled', 'pending'])
*/

/* ── AUTH ROUTES ──────────────────────────────────────── */
app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    if (!email || !password) return res.status(400).json({ error: 'Email and password required' });
    const users = await q('SELECT * FROM flw_users WHERE email = ? AND deleted_at IS NULL LIMIT 1', [email]);
    if (!users.length) return res.status(401).json({ error: 'Invalid credentials' });
    const user = users[0];
    if (!verifyPassword(password, user.password_hash, user.password_salt))
      return res.status(401).json({ error: 'Invalid credentials' });
    const token = signToken({ id: user.id, email: user.email, name: user.name, role: user.role });
    res.json({ token, user: { id: user.id, email: user.email, name: user.name, role: user.role } });
  } catch (e) { res.status(500).json({ error: e.message }); }
});


// Parse arr_tags JSON array → comma-separated tag string
// mysql2 may auto-parse JSON columns into JS objects already
function parseArrTags(arr_tags) {
  if (!arr_tags) return '';
  // Already a JS array (mysql2 auto-parsed)
  if (Array.isArray(arr_tags)) return arr_tags.filter(Boolean).join(', ');
  // Already a JS object somehow
  if (typeof arr_tags === 'object') return '';
  // String form
  const s = String(arr_tags).trim();
  if (!s || s === 'null' || s === '[]') return '';
  try {
    const parsed = JSON.parse(s);
    if (Array.isArray(parsed)) return parsed.filter(Boolean).join(', ');
    if (typeof parsed === 'string') return parsed;
  } catch {}
  return s;
}

// Merge arr_tags + product_tags into one string (deduplicated)
function mergeTags(arr_tags, productTagsStr) {
  const a = parseArrTags(arr_tags).split(',').map(t=>t.trim()).filter(Boolean);
  const b = (productTagsStr||'').split(',').map(t=>t.trim()).filter(Boolean);
  const merged = [...new Set([...a, ...b])];
  return merged.join(', ');
}

app.get('/api/auth/me', auth, async (req, res) => {
  try {
    const rows = await q('SELECT id,email,name,role FROM flw_users WHERE id=? AND deleted_at IS NULL', [req.user.id]);
    if (!rows.length) return res.status(401).json({ error: 'User not found' });
    res.json(rows[0]);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/auth/users', auth, adminOnly, async (req, res) => {
  try { res.json(await q('SELECT id,email,name,role,created_at FROM flw_users WHERE deleted_at IS NULL ORDER BY created_at DESC')); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/auth/users', auth, adminOnly, async (req, res) => {
  try {
    const { email, name, password, role='viewer' } = req.body;
    if (!email || !password) return res.status(400).json({ error: 'Email and password required' });
    const { hash, salt } = hashPassword(password);
    await q('INSERT INTO flw_users (email,name,password_hash,password_salt,role,created_at) VALUES(?,?,?,?,?,NOW())', [email,name,hash,salt,role]);
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/auth/users/:id/delete', auth, adminOnly, async (req, res) => {
  try {
    if (parseInt(req.params.id) === req.user.id) return res.status(400).json({ error: 'Cannot delete yourself' });
    await q('UPDATE flw_users SET deleted_at=NOW() WHERE id=?', [req.params.id]);
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── WEBSITES ─────────────────────────────────────────── */
app.get('/api/websites', auth, async (req, res) => {
  try { res.json(await qc('SELECT id,name,platform,url FROM websites WHERE is_show=1 ORDER BY name')); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── LATEST DATE ──────────────────────────────────────── */
app.get('/api/latest-date', auth, async (req, res) => {
  try {
    const w = wf(req.query.website_id);
    const rows = await qc(
      `SELECT DATE_FORMAT(MAX(date_revenue),'%Y-%m-%d') AS latest FROM revenues WHERE deleted_at IS NULL${w.sql}`,
      w.params
    );
    res.json({ latest: rows[0]?.latest || new Date().toISOString().slice(0,10) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── REVENUE KPI ──────────────────────────────────────── */
/*
  From source: revenues table columns used:
  total_sale, gross_sale, net_sale, total_order, total_quantity,
  total_cog (NO 's'), total_shipping, total_tax, total_refunds,
  payment_fee, total_customers, discount_coupon, tip,
  facebook_ads, google_ads, bing_ads, email_ads
*/
const KPI_FIELDS = `
  COALESCE(SUM(total_sale),      0) AS revenue,
  COALESCE(SUM(total_order),     0) AS orders,
  COALESCE(SUM(total_quantity),  0) AS units,
  COALESCE(SUM(total_cog),       0) AS cogs,
  COALESCE(SUM(facebook_ads),    0) AS fb_spend,
  COALESCE(SUM(google_ads),      0) AS ga_cost,
  COALESCE(SUM(bing_ads),        0) AS bing_spend,
  COALESCE(SUM(email_ads),       0) AS email_spend,
  COALESCE(SUM(facebook_ads+google_ads+bing_ads+email_ads), 0) AS ad_spend,
  COALESCE(SUM(total_refunds),   0) AS refunds,
  COALESCE(SUM(total_shipping),  0) AS shipping,
  COALESCE(SUM(payment_fee),     0) AS payment_fee,
  COALESCE(SUM(total_customers), 0) AS customers,
  COALESCE(SUM(discount_coupon), 0) AS discounts,
  COALESCE(SUM(total_tax),       0) AS total_tax,
  COALESCE(SUM(tip),             0) AS tip`;

function kpiSQL(extraWhere = '') {
  return `SELECT ${KPI_FIELDS} FROM revenues WHERE deleted_at IS NULL AND date_revenue >= ? AND date_revenue < DATE_ADD(?, INTERVAL 1 DAY)${extraWhere}`;
}

/*
  From source (dailyReportCompare):
    profit = total_sale - total_cog - total_tax - payment_fee - total_ads - total_refunds
    total_sale (display) = total_sale - tip
    margin = profit / (total_sale - tip) * 100
    aov    = (total_sale - tip) / total_order
    roas   = (total_sale - tip) / total_ads
*/
function derived(k) {
  const sale_display = k.revenue - k.tip;
  const gross_profit = sale_display - k.cogs;
  const net_profit   = k.revenue - k.cogs - k.total_tax - k.payment_fee - k.ad_spend - k.refunds;
  const aov          = k.orders > 0 ? sale_display / k.orders : 0;
  const roas         = k.ad_spend > 0 ? sale_display / k.ad_spend : 0;
  const margin       = sale_display > 0 ? net_profit / sale_display * 100 : 0;
  const refund_rate  = sale_display > 0 ? k.refunds / sale_display * 100 : 0;
  return { sale_display, gross_profit, net_profit, aov, roas, margin, refund_rate };
}

/* ── EXEC / KPIs ──────────────────────────────────────── */
app.get('/api/exec/kpis', auth, async (req, res) => {
  try {
    const { start, end, website_id, compare } = req.query;
    const [s, e] = dateRange(start, end);
    console.log("[daily/products] start=%s end=%s website=%s", s, e, website_id);
    const w = wf(website_id);

    const [k] = await q(kpiSQL(w.sql), [s, e, ...w.params]);
    const d   = derived(k);

    let compareData = {};
    if (compare && compare !== 'none') {
      try {
        const ds=new Date(s.slice(0,10)+'T12:00:00'), de=new Date(e.slice(0,10)+'T12:00:00');
        const days=Math.round((de-ds)/86400000)+1;
        const fmt=d=>d.toISOString().slice(0,10);
        let ps,pe;
        if (compare==='prev_period') { pe=new Date(ds); pe.setDate(pe.getDate()-1); ps=new Date(pe); ps.setDate(ps.getDate()-days+1); }
        else if (compare==='prev_month') { ps=new Date(ds); ps.setMonth(ps.getMonth()-1); pe=new Date(de); pe.setMonth(pe.getMonth()-1); }
        else if (compare==='prev_year')  { ps=new Date(ds); ps.setFullYear(ps.getFullYear()-1); pe=new Date(de); pe.setFullYear(pe.getFullYear()-1); }
        if (ps && pe) {
          const [pk] = await q(kpiSQL(w.sql), [fmt(ps), fmt(pe), ...w.params]);
          const pd   = derived(pk);
          const dlt  = (c,p) => Math.abs(p)>0 ? (c-p)/Math.abs(p)*100 : null;
          compareData = {
            compare_label: `${fmt(ps)} to ${fmt(pe)}`, compare_start: fmt(ps), compare_end: fmt(pe),
            delta_revenue: dlt(k.revenue, pk.revenue), delta_orders: dlt(k.orders, pk.orders),
            delta_aov: dlt(d.aov, pd.aov), delta_ad_spend: dlt(k.ad_spend, pk.ad_spend),
            delta_roas: dlt(d.roas, pd.roas), delta_gross_profit: dlt(d.gross_profit, pd.gross_profit),
            delta_net_profit: dlt(d.net_profit, pd.net_profit), delta_margin: d.margin - pd.margin,
            delta_refunds: dlt(k.refunds, pk.refunds),
          };
        }
      } catch(compareErr) { /* ignore compare errors */ }
    }
    res.json({ ...k, ...d, ...compareData });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── EXEC / TREND ─────────────────────────────────────── */
app.get('/api/exec/trend', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id);
    res.json(await qc(`
      SELECT DATE(date_revenue) AS date,
        SUM(total_sale) AS revenue,
        SUM(total_sale - tip) AS sale_display,
        SUM(total_order) AS orders,
        SUM(facebook_ads+google_ads+bing_ads+email_ads) AS ad_spend,
        SUM(total_cog) AS cogs,
        SUM(total_sale) - SUM(total_cog) - SUM(total_tax)
          - SUM(payment_fee) - SUM(facebook_ads+google_ads+bing_ads+email_ads)
          - SUM(total_refunds) AS net_profit,
        SUM(total_shipping) AS shipping, SUM(total_refunds) AS refunds
      FROM revenues WHERE deleted_at IS NULL AND date_revenue >= ? AND date_revenue < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}
      GROUP BY DATE(date_revenue) ORDER BY date ASC`, [s, e, ...w.params]));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── EXEC / REVENUE BY WEBSITE ────────────────────────── */
app.get('/api/exec/websites', auth, async (req, res) => {
  try {
    const { start, end } = req.query;
    const [s, e] = dateRange(start, end);
    res.json(await qc(`
      SELECT w.name AS website, w.id AS website_id,
        SUM(r.total_sale) AS revenue, SUM(r.total_order) AS orders
      FROM revenues r JOIN websites w ON w.id=r.website_id
      WHERE r.deleted_at IS NULL AND w.is_show=1 AND r.date_revenue >= ? AND r.date_revenue < DATE_ADD(?, INTERVAL 1 DAY)
      GROUP BY w.id,w.name ORDER BY revenue DESC`, [s, e]));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── EXEC / TOP PRODUCTS ──────────────────────────────── */
/*
  From source: SUM(subtotal * quantity) not SUM(subtotal)
  Exclude failed/cancelled/pending orders
*/
app.get('/api/exec/top-products', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id, 'o');
    const topRows = await qc(`
      SELECT li.parent_name AS name, MAX(li.product_id) AS product_id,
        SUM(li.subtotal * li.quantity) AS revenue,
        COUNT(DISTINCT o.order_number) AS orders,
        SUM(li.quantity) AS units
      FROM line_items_orders li
      JOIN orders o ON o.id = li.order_id AND o.deleted_at IS NULL
      JOIN websites ws ON ws.id = o.website_id AND ws.is_show = 1
      WHERE li.deleted_at IS NULL
        AND o.status NOT IN ('failed','cancelled','pending')
        AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}
      GROUP BY li.parent_name
      ORDER BY revenue DESC LIMIT 10`, [s, e, ...w.params]);

    // Fetch images separately with IN clause (much faster than JOIN)
    const pids = topRows.map(r=>r.product_id).filter(Boolean);
    let imgMap = {};
    if (pids.length) {
      const imgs = await q(
        `SELECT product_id, image FROM products WHERE product_id IN (${pids.map(()=>'?').join(',')}) AND deleted_at IS NULL`,
        pids
      );
      imgs.forEach(r => { imgMap[r.product_id] = r.image; });
    }
    res.json(topRows.map(r => ({ ...r, image: imgMap[r.product_id] || null })));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── DAILY / PERIODS ──────────────────────────────────── */
/*
  From source: revenues table directly, profit formula matches dailyReportCompare
*/
app.get('/api/daily/periods', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id);
    res.json(await qc(`
      SELECT DATE(date_revenue) AS date,
        SUM(total_sale - tip) AS sales,
        SUM(total_order) AS orders,
        SUM(total_quantity) AS units,
        SUM(total_cog) AS cogs,
        SUM(facebook_ads+google_ads+bing_ads+email_ads) AS ads,
        SUM(total_refunds) AS refunds,
        SUM(total_shipping) AS shipping,
        SUM(payment_fee) AS payment_fee,
        SUM(total_customers) AS customers,
        SUM(total_tax) AS tax,
        SUM(discount_coupon) AS discounts,
        SUM(tip) AS tip,
        SUM(total_sale) - SUM(total_cog) - SUM(total_tax)
          - SUM(payment_fee) - SUM(facebook_ads+google_ads+bing_ads+email_ads)
          - SUM(total_refunds) AS net_profit,
        CASE WHEN SUM(total_order)>0
          THEN (SUM(total_sale)-SUM(tip)) / SUM(total_order) END AS aov,
        CASE WHEN SUM(facebook_ads+google_ads+bing_ads+email_ads)>0
          THEN (SUM(total_sale)-SUM(tip)) / SUM(facebook_ads+google_ads+bing_ads+email_ads) END AS roas
      FROM revenues WHERE deleted_at IS NULL AND date_revenue >= ? AND date_revenue < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}
      GROUP BY DATE(date_revenue) ORDER BY date DESC`, [s, e, ...w.params]));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── DAILY / PRODUCTS ─────────────────────────────────── */
/*
  From source (getProductRevenueDailyReport / getProductWebsiteReport):
  - SUM(subtotal * quantity) for revenue — NOT SUM(subtotal)
  - MAX(li.sku) for parent_sku — sku is in line_items_orders
  - MAX(li.image) for image — image is in line_items_orders (json)
  - Tags fetched via product_tags JOIN tags WHERE product_tags.product_id = products.id
  - google_ads cost/revenue from google_ads table by product_id
  - Exclude: failed/cancelled/pending orders
  - Group by: parent_name, website_name (NOT product_id to match source behavior)
*/
app.get('/api/daily/products', auth, async (req, res) => {
  try {
    const { start, end, website_id, page=1, per=50, search } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id, 'o');
    const sp = search ? [`%${search}%`] : [];
    const ss = search ? ' AND li.parent_name LIKE ?' : '';
    const offset = (parseInt(page)-1)*parseInt(per);

    const baseWhere = `
      WHERE li.deleted_at IS NULL
        AND o.status NOT IN ('failed','cancelled','pending')
        AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}${ss}`;

    const [rows, [cntRow]] = await Promise.all([
      q(`SELECT
          li.parent_name,
          ws.name AS website_name,
          MAX(li.image) AS image,
          MAX(li.sku) AS parent_sku,
          MAX(li.product_type) AS product_type,
          MAX(li.product_id) AS product_id,
          COUNT(DISTINCT o.order_number) AS total_orders,
          SUM(li.quantity) AS product_quantity,
          SUM(li.subtotal * li.quantity) AS sub_total,
          SUM(li.total_cogs) AS total_cogs,
          SUM(li.total_tax) AS total_taxes,
          SUM(li.discount_total) AS discount,
          MAX(p.id) AS internal_product_id,
          COALESCE(MAX(p.platform), 'unknown') AS platform,
          MAX(p.arr_tags) AS arr_tags,
          MAX(p.date_created) AS date_created
        FROM line_items_orders li
        JOIN orders o    ON o.id = li.order_id AND o.deleted_at IS NULL
        JOIN websites ws ON ws.id = o.website_id AND ws.is_show = 1
        LEFT JOIN products p ON p.product_id = li.product_id AND p.deleted_at IS NULL
        ${baseWhere}
        GROUP BY li.parent_name, ws.name
        ORDER BY sub_total DESC
        LIMIT ? OFFSET ?`,
        [s, e, ...w.params, ...sp, parseInt(per), offset]),
      q(`SELECT COUNT(DISTINCT CONCAT_WS('||',li.parent_name, ws.name, COALESCE(p.platform,'_'))) AS total
        FROM line_items_orders li
        JOIN orders o    ON o.id = li.order_id AND o.deleted_at IS NULL
        JOIN websites ws ON ws.id = o.website_id AND ws.is_show = 1
        LEFT JOIN products p ON p.product_id = li.product_id AND p.deleted_at IS NULL
        ${baseWhere}`,
        [s, e, ...w.params, ...sp]),
    ]);

    // Attach google ads data and tags
    const productIds = rows.map(r => r.product_id).filter(Boolean);
    const internalIds = rows.map(r => r.internal_product_id).filter(Boolean);

    let gadsMap = {};
    if (productIds.length) {
      const gads = await q(`
        SELECT product_id, SUM(cost) AS cost, SUM(revenue) AS revenue
        FROM google_ads
        WHERE product_id IN (${productIds.map(()=>'?').join(',')})
          AND date_ads >= ? AND date_ads < DATE_ADD(?, INTERVAL 1 DAY)
          AND deleted_at IS NULL
        GROUP BY product_id`,
        [...productIds, s, e]
      );
      gads.forEach(g => { gadsMap[g.product_id] = g; });
    }

    let tagsMap = {};
    // Fetch tags via Shopify product_ids (more reliable than internal IDs since JOIN may miss some)
    if (productIds.length) {
      const ph = productIds.map(()=>'?').join(',');
      const tags = await q(`
        SELECT p.product_id AS shopify_product_id, p.id AS internal_id,
          GROUP_CONCAT(t.name ORDER BY t.name SEPARATOR ', ') AS tags
        FROM products p
        JOIN product_tags pt ON pt.product_id = p.id
        JOIN tags t ON t.id = pt.tag_id
        WHERE p.product_id IN (${ph}) AND p.deleted_at IS NULL
        GROUP BY p.product_id, p.id`,
        productIds
      );
      tags.forEach(t => {
        tagsMap[t.internal_id] = t.tags;
        // also index by shopify product_id for fallback
        if (!tagsMap['sp_'+t.shopify_product_id]) tagsMap['sp_'+t.shopify_product_id] = t.tags;
      });
    }

    function deriveParentSku(sku) {
      if (!sku) return null;
      if (sku.includes('-')) return sku.substring(0, sku.lastIndexOf('-'));
      return sku;
    }

    function parseTags(arr_tags, fallbackTags) {
      if (arr_tags) {
        try {
          const parsed = JSON.parse(arr_tags);
          if (Array.isArray(parsed) && parsed.length) return parsed.join(', ');
        } catch {}
        if (typeof arr_tags === 'string' && arr_tags.trim()) return arr_tags;
      }
      return fallbackTags || '';
    }

    // Fetch product_code via JSON_TABLE for each product's arr_tags
    // Pass internal product IDs to a batch query
    let productCodeMap = {};
    if (internalIds.length) {
      const ph2 = internalIds.map(()=>'?').join(',');
      const codes = await q(`
        SELECT p.id AS internal_id,
          (SELECT jt.tag
           FROM JSON_TABLE(p.arr_tags, '$[*]' COLUMNS (tag VARCHAR(255) PATH '$')) jt
           WHERE jt.tag REGEXP '^[A-Z]{2,3}[0-9]{2,4}'
              OR jt.tag REGEXP '^[A-Z]{3}-[0-9]{3,4}-'
           ORDER BY (jt.tag REGEXP '^[A-Z]{2,3}[0-9]{2,4}') DESC
           LIMIT 1
          ) AS product_code
        FROM products p
        WHERE p.id IN (${ph2}) AND p.arr_tags IS NOT NULL`,
        internalIds
      );
      codes.forEach(r => { if (r.product_code) productCodeMap[r.internal_id] = r.product_code; });
    }

    const result = rows.map(r => ({
      ...r,
      parent_sku:         deriveParentSku(r.parent_sku),
      product_code:       productCodeMap[r.internal_product_id] || null,
      tags:               mergeTags(r.arr_tags, tagsMap[r.internal_product_id] || tagsMap['sp_'+r.product_id]),
      google_ads_cost:    gadsMap[r.product_id]?.cost || 0,
      google_ads_revenue: gadsMap[r.product_id]?.revenue || 0,
    }));

    const total = parseInt(cntRow?.total) || 0;
    res.json({ rows: result, total, page: parseInt(page), pages: Math.ceil(total/parseInt(per)) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── ORDERS ───────────────────────────────────────────── */
/*
  From source (getOrderDataReport):
  - with('billingDetail', 'couponLines', 'lineItems', 'orderRefunds', 'taxes')
  - has('lineItems') — only orders with line items
  - whereHas('website', is_show=1)
  - No status exclusion on orders list (shows all statuses)
  - billing_details: one row per order (updateOrCreate by order_id) so no duplicates
*/
app.get('/api/orders', auth, async (req, res) => {
  try {
    const { start, end, website_id, status, search_order, search_email, search_coupon, page=1, per=20 } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id, 'o');
    const params = [s, e, ...w.params];
    let where = ` WHERE o.deleted_at IS NULL
      AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}
      AND o.website_id IN (SELECT id FROM websites WHERE is_show = 1)`;

    if (status && status !== 'all') { where += ' AND o.status = ?'; params.push(status); }
    if (search_order) {
      where += ' AND (o.order_number LIKE ? OR CAST(o.order_id AS CHAR) LIKE ?)';
      params.push(`%${search_order}%`, `%${search_order}%`);
    }
    if (search_email) {
      // Use EXISTS with date-filtered subquery to avoid full scan
      where += ' AND EXISTS (SELECT 1 FROM billing_details bd2 WHERE bd2.order_id=o.id AND bd2.email LIKE ?)';
      params.push(`%${search_email}%`);
    }

    const offset = (parseInt(page)-1)*parseInt(per);

    // Step 1: fast ID query (indexed date_created)
    const [cnt, idRows] = await Promise.all([
      q(`SELECT COUNT(*) AS total FROM orders o ${where}`, params),
      q(`SELECT o.id, o.order_id, o.order_number, o.status, o.date_created,
          o.total, o.discount_total, o.shipping_total, o.shipping_tax,
          o.total_tax, o.payment_fee, o.total_quantity,
          o.tracking_code, o.landing_site, o.payment_method, o.payment_method_title
        FROM orders o ${where}
        ORDER BY o.date_created DESC LIMIT ? OFFSET ?`, [...params, parseInt(per), offset]),
    ]);

    if (!idRows.length) {
      return res.json({ rows:[], total:0, page:parseInt(page), pages:0 });
    }

    // Step 2: lookup supporting data by order IDs only (no full table scan)
    const ids = idRows.map(r=>r.id);
    const ph  = ids.map(()=>'?').join(',');

    const [billings, coupons, refunds, products] = await Promise.all([
      q(`SELECT order_id, MAX(first_name) AS first_name, MAX(last_name) AS last_name,
          MAX(email) AS email, MAX(state) AS state, MAX(country) AS country, MAX(phone) AS phone
        FROM billing_details WHERE order_id IN (${ph}) GROUP BY order_id`, ids),
      q(`SELECT order_id, GROUP_CONCAT(code ORDER BY id SEPARATOR ', ') AS coupons
        FROM coupon_lines WHERE order_id IN (${ph}) AND deleted_at IS NULL GROUP BY order_id`, ids),
      q(`SELECT order_id, SUM(total) AS refund_total FROM refunds WHERE order_id IN (${ph}) GROUP BY order_id`, ids),
      q(`SELECT order_id, GROUP_CONCAT(DISTINCT parent_name ORDER BY id SEPARATOR ' | ') AS products_list
        FROM line_items_orders WHERE order_id IN (${ph}) AND deleted_at IS NULL GROUP BY order_id`, ids),
    ]);

    const bMap = {}; billings.forEach(r => bMap[r.order_id] = r);
    const cMap = {}; coupons.forEach(r  => cMap[r.order_id] = r.coupons);
    const rMap = {}; refunds.forEach(r  => rMap[r.order_id] = r.refund_total);
    const pMap = {}; products.forEach(r => pMap[r.order_id] = r.products_list);

    const rows = idRows.map(r => ({
      ...r,
      first_name:    bMap[r.id]?.first_name || null,
      last_name:     bMap[r.id]?.last_name  || null,
      email:         bMap[r.id]?.email      || null,
      state:         bMap[r.id]?.state      || null,
      country:       bMap[r.id]?.country    || null,
      phone:         bMap[r.id]?.phone      || null,
      coupons:       cMap[r.id] || null,
      refund_total:  rMap[r.id] || 0,
      products_list: pMap[r.id] || null,
    }));

    const total = parseInt(cnt[0]?.total) || 0;
    res.json({ rows, total, page:parseInt(page), pages:Math.ceil(total/parseInt(per)) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── ORDER / LINE ITEMS ───────────────────────────────── */
app.get('/api/orders/:id/items', auth, async (req, res) => {
  try {
    const rows = await q(`
      SELECT li.line_item_id, li.name, li.parent_name, li.sku,
        li.quantity, li.price, li.subtotal, li.total,
        li.total_tax, li.discount_total, li.total_cogs, li.product_type, li.tracking_id
      FROM line_items_orders li WHERE li.order_id = ? AND li.deleted_at IS NULL`,
      [req.params.id]);
    res.json(rows);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── PRODUCTS CATALOG ─────────────────────────────────── */
/*
  From source (ProductController.getDataProductReport):
  Tags via product_tags JOIN tags — separate query to avoid row multiplication
  Categories via product_categories JOIN categories — separate query
*/
app.get('/api/products', auth, async (req, res) => {
  try {
    const { website_id, search, status, page=1, per=20, start, end } = req.query;
    const [s, e] = dateRange(start, end);
    const wid = website_id && website_id !== 'all' && website_id !== '0' ? parseInt(website_id) : null;

    // Web report logic: filter products by date_created range + website
    // (not by orders — 202 = products created in Flagwix Shopify in Jan-Mar 2026)
    const params = [s, e];
    let where = `WHERE p.deleted_at IS NULL
      AND p.date_created >= ? AND p.date_created < DATE_ADD(?, INTERVAL 1 DAY)`;
    if (wid)                        { where += ' AND p.website_id = ?';  params.push(wid); }
    if (status && status !== 'all') { where += ' AND p.status = ?';      params.push(status); }
    if (search)                     { where += ' AND p.name LIKE ?';     params.push(`%${search}%`); }

    const offset = (parseInt(page)-1)*parseInt(per);

    const [rows, cnt] = await Promise.all([
      q(`SELECT p.product_id, p.id AS internal_id, p.name, p.status,
            p.date_created, p.date_modified, p.image, p.platform, p.arr_tags,
            w2.name AS website
          FROM products p LEFT JOIN websites w2 ON w2.id = p.website_id
          ${where}
          ORDER BY p.date_created DESC LIMIT ? OFFSET ?`,
        [...params, parseInt(per), offset]),
      q(`SELECT COUNT(*) AS total FROM products p ${where}`, params),
    ]);

    const internalIds = rows.map(r => r.internal_id).filter(Boolean);
    let tagsMap = {}, catsMap = {};
    if (internalIds.length) {
      const phi = internalIds.map(()=>'?').join(',');
      const [tags, cats] = await Promise.all([
        q(`SELECT pt.product_id, GROUP_CONCAT(t.name ORDER BY t.name SEPARATOR ', ') AS tags
           FROM product_tags pt JOIN tags t ON t.id = pt.tag_id
           WHERE pt.product_id IN (${phi}) GROUP BY pt.product_id`, internalIds),
        q(`SELECT pc.product_id, GROUP_CONCAT(c.name ORDER BY c.name SEPARATOR ', ') AS cats
           FROM product_categories pc JOIN categories c ON c.id = pc.category_id
           WHERE pc.product_id IN (${phi}) GROUP BY pc.product_id`, internalIds),
      ]);
      tags.forEach(t => { tagsMap[t.product_id] = t.tags; });
      cats.forEach(c => { catsMap[c.product_id] = c.cats; });
    }

    const total = parseInt(cnt[0]?.total) || 0;
    const result = rows.map(r => ({
      ...r,
      tags:       mergeTags(r.arr_tags, tagsMap[r.internal_id]),
      categories: catsMap[r.internal_id] || '',
    }));

    res.json({ rows: result, total, page: parseInt(page), pages: Math.ceil(total / parseInt(per)) });
  } catch (e) {
    console.error('[products] error:', e.message);
    res.status(500).json({ error: e.message });
  }
});


/* ── PRODUCT DETAIL (variants + gallery) ──────────────── */
app.get('/api/products/:pid/detail', auth, async (req, res) => {
  try {
    const { pid } = req.params;  // internal product id

    const [variants, gallery] = await Promise.all([
      q(`SELECT pv.product_variant_id, pv.sku, pv.status, pv.stock_status,
            pv.regular_price, pv.sale_price, pv.image,
            GROUP_CONCAT(CONCAT(pa.name,': ',pa.option) ORDER BY pa.name SEPARATOR ' | ') AS attributes
          FROM product_variants pv
          LEFT JOIN product_attributes pa ON pa.product_variant_id = pv.id
          WHERE pv.product_id = ? AND pv.deleted_at IS NULL
          GROUP BY pv.id ORDER BY pv.id`, [pid]),
      q(`SELECT pg.src, pg.alt, pg.name FROM product_galleries pg
          WHERE pg.product_id = ? ORDER BY pg.id`, [pid]),
    ]);

    res.json({ variants, gallery });
  } catch (e) { res.status(500).json({ error: e.message }); }
});


/* ── PRODUCT REPORT ───────────────────────────────────── */
/*
  Same logic as daily/products but different date range context
  subtotal = SUM(subtotal * quantity) from source
*/
app.get('/api/product-report', auth, async (req, res) => {
  try {
    const { start, end, website_id, product_name, page=1, per=50 } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id, 'o');
    const params = [s, e, ...w.params];
    let extra = product_name ? ' AND li.parent_name LIKE ?' : '';
    if (product_name) params.push(`%${product_name}%`);
    const offset = (parseInt(page)-1)*parseInt(per);

    // Step 1: group by parent_name+website (indexed date_created on orders)
    const [rows, [cntRow]] = await Promise.all([
      q(`SELECT
          li.parent_name, ws.name AS website_name,
          MAX(li.product_id) AS product_id,
          MAX(li.sku) AS parent_sku,
          MAX(li.product_type) AS product_type,
          COUNT(DISTINCT o.order_number) AS total_orders,
          SUM(li.quantity) AS product_quantity,
          SUM(li.subtotal * li.quantity) AS sub_total,
          SUM(li.total_cogs) AS total_cogs,
          SUM(li.total_tax) AS total_taxes,
          SUM(li.discount_total) AS discount
        FROM line_items_orders li
        JOIN orders o    ON o.id = li.order_id AND o.deleted_at IS NULL
        JOIN websites ws ON ws.id = o.website_id AND ws.is_show = 1
        WHERE li.deleted_at IS NULL
          AND o.status NOT IN ('failed','cancelled','pending')
          AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}${extra}
        GROUP BY li.parent_name, ws.name
        ORDER BY sub_total DESC LIMIT ? OFFSET ?`,
        [...params, parseInt(per), offset]),
      q(`SELECT COUNT(DISTINCT li.parent_name) AS total
        FROM line_items_orders li
        JOIN orders o    ON o.id = li.order_id AND o.deleted_at IS NULL
        JOIN websites ws ON ws.id = o.website_id AND ws.is_show = 1
        WHERE li.deleted_at IS NULL
          AND o.status NOT IN ('failed','cancelled','pending')
          AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}${extra}`,
        params),
    ]);

    if (!rows.length) {
      return res.json({ rows:[], total:0, page:parseInt(page), pages:0 });
    }

    // Step 2: lookup product images, tags, google ads by specific product IDs
    const productIds  = [...new Set(rows.map(r=>r.product_id).filter(Boolean))];
    const ph = productIds.length ? productIds.map(()=>'?').join(',') : null;

    const [products, gads] = await Promise.all([
      ph ? q(`SELECT p.product_id, p.image, p.id AS internal_id, p.platform, p.arr_tags, p.date_created
              FROM products p WHERE p.product_id IN (${ph}) AND p.deleted_at IS NULL`, productIds)
         : Promise.resolve([]),
      ph ? q(`SELECT product_id, SUM(cost) AS cost, SUM(revenue) AS revenue
              FROM google_ads
              WHERE product_id IN (${ph})
                AND date_ads >= ? AND date_ads < DATE_ADD(?, INTERVAL 1 DAY)
                AND deleted_at IS NULL
              GROUP BY product_id`, [...productIds, s, e])
         : Promise.resolve([]),
    ]);

    const prodMap = {}; products.forEach(p => prodMap[p.product_id] = p);
    const gadsMap = {}; gads.forEach(g => gadsMap[g.product_id] = g);

    // Fetch tags for found internal product IDs
    const internalIds = products.map(p=>p.internal_id).filter(Boolean);
    let tagsMap = {};
    if (internalIds.length) {
      const ph2 = internalIds.map(()=>'?').join(',');
      const tags = await q(`SELECT pt.product_id, GROUP_CONCAT(t.name ORDER BY t.name SEPARATOR ', ') AS tags
        FROM product_tags pt JOIN tags t ON t.id=pt.tag_id
        WHERE pt.product_id IN (${ph2}) GROUP BY pt.product_id`, internalIds);
      tags.forEach(t => { tagsMap[t.product_id] = t.tags; });
    }

    const result = rows.map(r => {
      const prod = prodMap[r.product_id] || {};
      return {
        ...r,
        image:              prod.image || null,
        platform:           prod.platform || r.platform || null,
        arr_tags:           prod.arr_tags || null,
        date_created:       prod.date_created || null,
        internal_product_id: prod.internal_id || null,
        google_ads_cost:    gadsMap[r.product_id]?.cost    || 0,
        google_ads_revenue: gadsMap[r.product_id]?.revenue || 0,
        tags:               mergeTags(prod.arr_tags, tagsMap[prod.internal_id]),
      };
    });

    const total = parseInt(cntRow?.total) || 0;
    res.json({ rows:result, total, page:parseInt(page), pages:Math.ceil(total/parseInt(per)) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── PLATFORM REPORT ──────────────────────────────────── */
/*
  From source (getReportPlatformByDateApi):
  - line_items subquery: exclude 'ADDITIONAL FEE%' and 'Tip' from quantity/cogs
  - tip = SUM(CASE WHEN parent_name='Tip' THEN total ELSE 0 END)
  - refunds: separate subquery SELECT order_id, SUM(total) AS total_refunds FROM refunds GROUP BY order_id
  - Group by DATE(date_created), landing_site, website_id
  - landing_site from orders table (confirmed)
*/
app.get('/api/platform-report', auth, async (req, res) => {
  try {
    const { start, end, website_id, search, page=1, per=50 } = req.query;
    const [s, e] = dateRange(start, end);
    const wid = website_id && website_id !== 'all' ? parseInt(website_id) : null;
    const params = [s, e, s, e];
    if (wid) params.push(wid, wid);

    let wJoin = wid ? ` AND ws.id = ? AND ws.platform = 'shopify'` : ` AND ws.platform = 'shopify'`;
    let wLineItem = wid ? ` AND website_id IN (SELECT id FROM websites WHERE id = ? AND platform = 'shopify')` : ` AND website_id IN (SELECT id FROM websites WHERE platform = 'shopify')`;
    let platformFilter = search ? ` AND (o.landing_site LIKE ? OR o.landing_site IS NULL)` : '';
    if (search) params.push(`%${search}%`);

    const offset = (parseInt(page)-1)*parseInt(per);
    params.push(parseInt(per), offset);

    const rows = await q(`
      SELECT
        DATE(o.date_created) AS date_revenue,
        COALESCE(NULLIF(o.landing_site,''),'direct') AS platform,
        ws.name AS website,
        o.website_id,
        COUNT(DISTINCT o.id) AS total_order,
        CAST(SUM(o.total) AS DECIMAL(15,2)) AS total_sales,
        CAST(SUM(o.total_tax) AS DECIMAL(15,2)) AS total_tax,
        CAST(SUM(o.payment_fee) AS DECIMAL(15,2)) AS payment_fee,
        CAST(SUM(o.shipping_total) AS DECIMAL(15,2)) AS shipping_total,
        CAST(SUM(o.discount_total) AS DECIMAL(15,2)) AS discount_total,
        CAST(COALESCE(SUM(li_data.total_quantity),0) AS DECIMAL(15,2)) AS total_quantity,
        CAST(COALESCE(SUM(li_data.tip),0) AS DECIMAL(15,2)) AS tip,
        CAST(COALESCE(SUM(li_data.total_cogs),0) AS DECIMAL(15,2)) AS total_cogs,
        CAST(COALESCE(SUM(ref_data.total_refunds),0) AS DECIMAL(15,2)) AS total_refunds
      FROM orders o
      JOIN websites ws ON ws.id = o.website_id${wJoin}
      LEFT JOIN (
        SELECT order_id,
          SUM(CASE WHEN parent_name NOT LIKE 'ADDITIONAL FEE%' AND parent_name != 'Tip' THEN quantity ELSE 0 END) AS total_quantity,
          SUM(CASE WHEN parent_name = 'Tip' THEN total ELSE 0 END) AS tip,
          SUM(CASE WHEN parent_name NOT LIKE 'ADDITIONAL FEE%' AND parent_name != 'Tip' THEN total_cogs ELSE 0 END) AS total_cogs
        FROM line_items_orders
        WHERE order_id IN (
          SELECT id FROM orders WHERE date_created >= ? AND date_created < DATE_ADD(?, INTERVAL 1 DAY)${wLineItem}
        )
        GROUP BY order_id
      ) li_data ON li_data.order_id = o.id
      LEFT JOIN (
        SELECT order_id, SUM(total) AS total_refunds FROM refunds GROUP BY order_id
      ) ref_data ON ref_data.order_id = o.id
      WHERE o.deleted_at IS NULL AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${platformFilter}
      GROUP BY DATE(o.date_created), COALESCE(NULLIF(o.landing_site,''),'direct'), o.website_id, ws.name
      ORDER BY date_revenue DESC, total_sales DESC
      LIMIT ? OFFSET ?`,
      params
    );
    const cntParams = params.slice(0, -2); // remove LIMIT/OFFSET

    // COUNT distinct date+platform+website combos
    const [[cnt]] = await Promise.all([
      q(`SELECT COUNT(*) AS total FROM (
          SELECT 1
          FROM orders o
          JOIN websites ws ON ws.id = o.website_id
          LEFT JOIN (
            SELECT order_id, SUM(total) AS total_refunds FROM refunds GROUP BY order_id
          ) ref_data ON ref_data.order_id = o.id
          WHERE o.deleted_at IS NULL AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${platformFilter}
          GROUP BY DATE(o.date_created), COALESCE(NULLIF(o.landing_site,''),'direct'), o.website_id, ws.name
        ) cnt`,
        cntParams
      ),
    ]);

    const total = parseInt(cnt?.total) || 0;
    res.json({ rows, total, page: parseInt(page), pages: Math.ceil(total / parseInt(per)) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* Platform report KPI summary (from revenues for accuracy) */
app.get('/api/platform-report/summary', auth, async (req, res) => {
  try {
    const { start, end, website_id, compare } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id);

    const [k] = await q(kpiSQL(w.sql), [s, e, ...w.params]);
    const d = derived(k);

    // Compute prev period for deltas
    const ds = new Date(s+'T12:00:00'), de = new Date(e+'T12:00:00');
    const days = Math.round((de-ds)/86400000)+1;
    const fmt = d => d.toISOString().slice(0,10);
    const pe = new Date(ds); pe.setDate(pe.getDate()-1);
    const ps = new Date(pe); ps.setDate(ps.getDate()-days+1);
    const [pk] = await q(kpiSQL(w.sql), [fmt(ps), fmt(pe), ...w.params]);
    const pd = derived(pk);

    const delta = (cur, prev) => prev > 0 ? ((cur - prev) / prev * 100).toFixed(1) : null;

    res.json({
      ...k, ...d,
      delta_revenue:     delta(d.revenue,     pd.revenue),
      delta_orders:      delta(k.orders,       pk.orders),
      delta_net_profit:  delta(d.net_profit,   pd.net_profit),
      delta_roas:        delta(d.roas,          pd.roas),
      prev_revenue:      pd.revenue,
      prev_orders:       pk.orders,
    });
  } catch (e) { res.status(500).json({ error: e.message }); }
});


/* ── FACEBOOK ADS ────────────────────────────────────── */
/*
  Data stored in `facebook_campaigns` table.
  JOIN `facebook_ads_accounts` on account_id to get account name + website filter.
  Fields: campaign_id, account_id, date_ads, campaign_name,
          total_spend, total_revenue, total_impressions, total_clicks
*/
app.get('/api/facebook-ads/summary', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const params = [s, e];
    let where = ' WHERE fc.date_ads >= ? AND fc.date_ads < DATE_ADD(?, INTERVAL 1 DAY)';
    if (website_id && website_id !== 'all') { where += ' AND faa.website_id = ?'; params.push(website_id); }
    else { where += ' AND faa.website_id IN (SELECT id FROM websites WHERE is_show=1)'; }

    const [summary] = await q(`
      SELECT
        COALESCE(SUM(fc.total_spend),0)       AS total_cost,
        COALESCE(SUM(fc.total_revenue),0)     AS total_revenue,
        COALESCE(SUM(fc.total_clicks),0)      AS total_clicks,
        COALESCE(SUM(fc.total_impressions),0) AS total_impressions,
        CASE WHEN SUM(fc.total_spend)>0 THEN SUM(fc.total_revenue)/SUM(fc.total_spend) ELSE 0 END AS roas
      FROM facebook_campaigns fc
      JOIN facebook_ads_accounts faa ON faa.account_id = fc.account_id
      ${where}`, params);
    res.json(summary || {});
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/facebook-ads', auth, async (req, res) => {
  try {
    const { start, end, website_id, search } = req.query;
    const [s, e] = dateRange(start, end);
    const params = [s, e];
    let where = ' WHERE fc.date_ads >= ? AND fc.date_ads < DATE_ADD(?, INTERVAL 1 DAY)';
    if (website_id && website_id !== 'all') { where += ' AND faa.website_id = ?'; params.push(website_id); }
    else { where += ' AND faa.website_id IN (SELECT id FROM websites WHERE is_show=1)'; }
    if (search) { where += ' AND fc.campaign_name LIKE ?'; params.push(`%${search}%`); }

    const rows = await q(`
      SELECT
        fc.id, fc.campaign_id, fc.campaign_name,
        fc.date_ads AS date,
        fc.total_spend  AS spend,
        fc.total_revenue AS revenue,
        fc.total_impressions AS impressions,
        fc.total_clicks AS clicks,
        CASE WHEN fc.total_spend>0 THEN fc.total_revenue/fc.total_spend ELSE 0 END AS roas,
        ws.name AS website,
        faa.name AS account_name
      FROM facebook_campaigns fc
      JOIN facebook_ads_accounts faa ON faa.account_id = fc.account_id
      JOIN websites ws ON ws.id = faa.website_id
      ${where}
      ORDER BY fc.date_ads DESC, fc.total_spend DESC`, params);

    res.json({ rows, total: rows.length, pages: 1 });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── GOOGLE ADS CAMPAIGN ──────────────────────────────── */
/*
  Data stored in `campaign_daily_ads` table (ALL rows = Google Ads, no FB filter needed).
  Fields: website_id, date_ads, campaign_id, campaign_name,
          cost, revenue, impressions, clicks, conversions, roas, status
*/
app.get('/api/google-ads', auth, async (req, res) => {
  try {
    const { start, end, website_id, status, search } = req.query;
    const [s, e] = dateRange(start, end);
    const params = [s, e];
    let where = ' WHERE cda.date_ads >= ? AND cda.date_ads < DATE_ADD(?, INTERVAL 1 DAY)';
    if (website_id && website_id !== 'all') { where += ' AND cda.website_id = ?'; params.push(website_id); }
    else { where += ' AND cda.website_id IN (SELECT id FROM websites WHERE is_show=1)'; }
    if (status && status !== 'all') { where += ' AND cda.status = ?'; params.push(status); }
    if (search) { where += ' AND cda.campaign_name LIKE ?'; params.push(`%${search}%`); }

    const [rows, [summary]] = await Promise.all([
      q(`SELECT
          ws.name AS website, cda.date_ads AS date,
          cda.campaign_id, cda.campaign_name, cda.status,
          cda.cost, cda.revenue, cda.impressions, cda.clicks,
          cda.conversions, cda.roas
        FROM campaign_daily_ads cda
        LEFT JOIN websites ws ON ws.id = cda.website_id
        ${where}
        ORDER BY cda.date_ads DESC, cda.cost DESC`, params),
      q(`SELECT
          COALESCE(SUM(cda.cost),0)        AS total_cost,
          COALESCE(SUM(cda.revenue),0)     AS total_revenue,
          COALESCE(SUM(cda.clicks),0)      AS total_clicks,
          COALESCE(SUM(cda.impressions),0) AS total_impressions,
          COALESCE(SUM(cda.conversions),0) AS total_conversions,
          CASE WHEN SUM(cda.cost)>0 THEN SUM(cda.revenue)/SUM(cda.cost) ELSE 0 END AS roas
        FROM campaign_daily_ads cda ${where}`, params),
    ]);
    res.json({ rows, summary: summary || {}, total: rows.length, pages: 1 });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── GOOGLE ADS PRODUCT ───────────────────────────────── */
/*
  Data stored in `google_ads` table.
  Fields: website_id, date_ads, product_title, product_sku,
          product_id, variant_id, impressions, clicks, cost, revenue, conversions, roas
*/
app.get('/api/google-ads/products', auth, async (req, res) => {
  try {
    const { start, end, website_id, search, sort='cost', page=1, per=50 } = req.query;
    const [s, e] = dateRange(start, end);
    const params = [s, e];
    let where = ' WHERE ga.deleted_at IS NULL AND ga.date_ads >= ? AND ga.date_ads < DATE_ADD(?, INTERVAL 1 DAY)';
    if (website_id && website_id !== 'all') { where += ' AND ga.website_id = ?'; params.push(website_id); }
    else { where += ' AND ga.website_id IN (SELECT id FROM websites WHERE is_show=1)'; }
    if (search) { where += ' AND ga.product_title LIKE ?'; params.push(`%${search}%`); }
    const safeSort = ['cost','revenue','clicks','impressions','roas','conversions'].includes(sort) ? sort : 'cost';
    const offset = (parseInt(page)-1)*parseInt(per);

    const [rows, [summary]] = await Promise.all([
      q(`SELECT
          ws.name AS website_name, DATE(ga.date_ads) AS date,
          ga.product_title AS product, ga.product_id, ga.variant_id, ga.product_sku,
          ga.impressions, ga.clicks, ga.cost, ga.revenue,
          ROUND(ga.conversions, 2) AS conversions,
          ROUND(ga.roas, 2) AS roas
        FROM google_ads ga
        LEFT JOIN websites ws ON ws.id = ga.website_id
        ${where}
        ORDER BY ga.${safeSort} DESC
        LIMIT ? OFFSET ?`, [...params, parseInt(per), offset]),
      q(`SELECT
          COALESCE(SUM(ga.cost),0)    AS total_cost,
          COALESCE(SUM(ga.revenue),0) AS total_revenue,
          COALESCE(SUM(ga.clicks),0)  AS total_clicks,
          COUNT(*) AS total_rows
        FROM google_ads ga ${where}`, params),
    ]);
    const gaProdTotal = parseInt(summary?.total_rows||0);
    res.json({ rows, summary: summary || {}, total: gaProdTotal, pages: Math.ceil(gaProdTotal/parseInt(per)) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});


app.get('/api/profit', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id);

    const [summary] = await q(`
      SELECT SUM(total_sale) AS revenue, SUM(total_cog) AS cogs,
        SUM(facebook_ads) AS fb_ads, SUM(google_ads) AS ga_ads,
        SUM(bing_ads) AS bing_ads, SUM(email_ads) AS email_ads,
        SUM(facebook_ads+google_ads+bing_ads+email_ads) AS total_ads,
        SUM(total_shipping) AS shipping, SUM(total_refunds) AS refunds,
        SUM(payment_fee) AS payment_fee, SUM(tip) AS tip,
        SUM(total_sale-tip) - SUM(total_cog) AS gross_profit,
        SUM(total_sale) - SUM(total_cog) - SUM(total_tax)
          - SUM(payment_fee) - SUM(facebook_ads+google_ads+bing_ads+email_ads)
          - SUM(total_refunds) AS net_profit
      FROM revenues WHERE deleted_at IS NULL AND date_revenue >= ? AND date_revenue < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}`,
      [s, e, ...w.params]);

    const monthly = await qc(`
      SELECT DATE_FORMAT(date_revenue,'%Y-%m') AS month,
        SUM(total_sale-tip) AS revenue, SUM(total_cog) AS cogs,
        SUM(facebook_ads+google_ads+bing_ads+email_ads) AS ads,
        SUM(total_sale) - SUM(total_cog) - SUM(total_tax)
          - SUM(payment_fee) - SUM(facebook_ads+google_ads+bing_ads+email_ads)
          - SUM(total_refunds) AS net_profit,
        CASE WHEN SUM(total_sale-tip)>0 THEN
          (SUM(total_sale) - SUM(total_cog) - SUM(total_tax)
            - SUM(payment_fee) - SUM(facebook_ads+google_ads+bing_ads+email_ads)
            - SUM(total_refunds)) / SUM(total_sale-tip) * 100 ELSE 0 END AS margin
      FROM revenues WHERE deleted_at IS NULL
      GROUP BY DATE_FORMAT(date_revenue,'%Y-%m') ORDER BY month DESC LIMIT 12`);

    const byStore = await qc(`
      SELECT ws.name AS store,
        SUM(r.total_sale-r.tip) AS revenue,
        SUM(r.total_sale) - SUM(r.total_cog) - SUM(r.total_tax)
          - SUM(r.payment_fee) - SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads)
          - SUM(r.total_refunds) AS net_profit,
        CASE WHEN SUM(r.total_sale-r.tip)>0 THEN
          (SUM(r.total_sale) - SUM(r.total_cog) - SUM(r.total_tax)
            - SUM(r.payment_fee) - SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads)
            - SUM(r.total_refunds)) / SUM(r.total_sale-r.tip) * 100 ELSE 0 END AS margin
      FROM revenues r JOIN websites ws ON ws.id=r.website_id
      WHERE r.deleted_at IS NULL AND r.date_revenue >= ? AND r.date_revenue < DATE_ADD(?, INTERVAL 1 DAY)
      GROUP BY ws.id,ws.name ORDER BY revenue DESC`, [s, e]);

    res.json({ summary: summary||{}, monthly, byStore });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── CUSTOMERS ────────────────────────────────────────── */

app.get('/api/customers', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id, 'o');
    const params = [s, e, ...w.params];
    const where = ` WHERE o.deleted_at IS NULL AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}`;

    // Simple LEFT JOIN - MySQL filters orders first (indexed date_created), then looks up billing by order_id
    const [[summary], byState, byCountry] = await Promise.all([
      q(`SELECT COUNT(DISTINCT bd.email) AS total_customers,
          AVG(o.total) AS avg_order_value, COUNT(DISTINCT o.id) AS total_orders
        FROM orders o LEFT JOIN billing_details bd ON bd.order_id = o.id
        ${where}`, params),
      q(`SELECT bd.state, COUNT(DISTINCT o.id) AS orders, SUM(o.total) AS revenue
        FROM orders o LEFT JOIN billing_details bd ON bd.order_id = o.id
        ${where} AND bd.country = 'US' AND bd.state IS NOT NULL AND bd.state != ''
        GROUP BY bd.state ORDER BY revenue DESC LIMIT 20`, params),
      q(`SELECT bd.country, COUNT(DISTINCT o.id) AS orders, SUM(o.total) AS revenue
        FROM orders o LEFT JOIN billing_details bd ON bd.order_id = o.id
        ${where} AND bd.country IS NOT NULL AND bd.country != ''
        GROUP BY bd.country ORDER BY revenue DESC LIMIT 10`, params),
    ]);

    res.json({ summary: summary||{}, byState, byCountry });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── REFUNDS & COUPONS ────────────────────────────────── */
/*
  From source (updateRefundsReport): refunds.total = amount from Shopify/WooCommerce
  refunds.created_at is the date (no date_refund column in schema)
*/

app.get('/api/refunds', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const wr = wf(website_id, 'r');
    const wo = wf(website_id, 'o');
    const rP = [s, e, ...wr.params];
    const oP = [s, e, ...wo.params];

    const [summary] = await q(`
      SELECT COUNT(*) AS total_refunds, SUM(r.total) AS refund_value,
        COUNT(DISTINCT r.order_id) AS refunded_orders
      FROM refunds r WHERE r.created_at >= ? AND r.created_at < DATE_ADD(?, INTERVAL 1 DAY)${wr.sql}`, rP);

    const trend = await q(`
      SELECT DATE(r.created_at) AS date, COUNT(*) AS count, SUM(r.total) AS amount
      FROM refunds r WHERE r.created_at >= ? AND r.created_at < DATE_ADD(?, INTERVAL 1 DAY)${wr.sql}
      GROUP BY DATE(r.created_at) ORDER BY date ASC`, rP);

    const coupons = await q(`
      SELECT cl.code, cl.type, COUNT(*) AS uses, SUM(cl.discount) AS total_discount
      FROM coupon_lines cl JOIN orders o ON o.order_id = cl.order_id
      WHERE o.deleted_at IS NULL AND cl.deleted_at IS NULL
        AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${wo.sql}
      GROUP BY cl.code, cl.type ORDER BY uses DESC LIMIT 20`, oP);

    res.json({ summary: summary||{}, trend, coupons });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── SHOP COMPARISON ──────────────────────────────────── */

app.get('/api/shop-comparison', auth, async (req, res) => {
  try {
    const { start, end } = req.query;
    const [s, e] = dateRange(start, end);
    const [byStore, monthly] = await Promise.all([
      qc(`SELECT ws.id, ws.name AS store, ws.url,
          SUM(r.total_sale-r.tip) AS revenue, SUM(r.total_order) AS orders,
          CASE WHEN SUM(r.total_order)>0 THEN SUM(r.total_sale-r.tip)/SUM(r.total_order) ELSE 0 END AS aov,
          SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads) AS ad_spend,
          CASE WHEN SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads)>0
            THEN SUM(r.total_sale-r.tip)/SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads) ELSE 0 END AS roas,
          SUM(r.total_sale) - SUM(r.total_cog) - SUM(r.total_tax)
            - SUM(r.payment_fee) - SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads)
            - SUM(r.total_refunds) AS net_profit,
          CASE WHEN SUM(r.total_sale-r.tip)>0 THEN
            (SUM(r.total_sale) - SUM(r.total_cog) - SUM(r.total_tax)
              - SUM(r.payment_fee) - SUM(r.facebook_ads+r.google_ads+r.bing_ads+r.email_ads)
              - SUM(r.total_refunds)) / SUM(r.total_sale-r.tip) * 100 ELSE 0 END AS margin
        FROM revenues r JOIN websites ws ON ws.id=r.website_id
        WHERE r.deleted_at IS NULL AND ws.is_show=1 AND r.date_revenue >= ? AND r.date_revenue < DATE_ADD(?, INTERVAL 1 DAY)
        GROUP BY ws.id,ws.name,ws.url ORDER BY revenue DESC`, [s, e]),
      qc(`SELECT ws.name AS store, DATE_FORMAT(r.date_revenue,'%Y-%m') AS month,
          SUM(r.total_sale-r.tip) AS revenue
        FROM revenues r JOIN websites ws ON ws.id=r.website_id
        WHERE r.deleted_at IS NULL AND ws.is_show=1
        GROUP BY ws.name, DATE_FORMAT(r.date_revenue,'%Y-%m')
        ORDER BY month DESC, revenue DESC`),
    ]);
    res.json({ byStore, monthly });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── OPERATIONS ───────────────────────────────────────── */

app.get('/api/operations', auth, async (req, res) => {
  try {
    const { start, end, website_id } = req.query;
    const [s, e] = dateRange(start, end);
    const w = wf(website_id, 'o');
    const params = [s, e, ...w.params];
    const where = ` WHERE o.deleted_at IS NULL AND o.date_created >= ? AND o.date_created < DATE_ADD(?, INTERVAL 1 DAY)${w.sql}`;

    const byStatus = await q(`
      SELECT o.status, COUNT(*) AS count FROM orders o ${where}
      GROUP BY o.status ORDER BY count DESC`, params);

    const byShipping = await q(`
      SELECT sl.method_title, COUNT(*) AS count, SUM(sl.total) AS revenue
      FROM shipping_lines sl JOIN orders o ON o.order_id = sl.order_id
      ${where} AND sl.deleted_at IS NULL
      GROUP BY sl.method_title ORDER BY count DESC LIMIT 10`, params);

    res.json({ byStatus, byShipping });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── STATIC + SPA ─────────────────────────────────────── */
app.use(express.static(join(__dirname, 'dist')));
app.get('*', (req, res) => {
  if (req.path.startsWith('/api')) return res.status(404).json({ error: 'Not found' });
  res.sendFile(join(__dirname, 'dist', 'index.html'));
});

/* ── INIT DB ──────────────────────────────────────────── */
async function initDb() {
  if (!pool) return;
  try {
    await q(`CREATE TABLE IF NOT EXISTS flw_users (
      id INT AUTO_INCREMENT PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL,
      name VARCHAR(255), password_hash VARCHAR(200) NOT NULL, password_salt VARCHAR(100) NOT NULL,
      role ENUM('admin','viewer') DEFAULT 'viewer',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      deleted_at TIMESTAMP NULL)`);
    const ex = await q('SELECT id FROM flw_users WHERE email=? LIMIT 1', [process.env.ADMIN_EMAIL||'admin@flw.com']);
    if (!ex.length) {
      const { hash, salt } = hashPassword(process.env.ADMIN_PASSWORD||'changeme123');
      await q('INSERT INTO flw_users (email,name,password_hash,password_salt,role) VALUES(?,?,?,?,?)',
        [process.env.ADMIN_EMAIL||'admin@flw.com','Admin',hash,salt,'admin']);
      console.log('Admin user created:', process.env.ADMIN_EMAIL||'admin@flw.com');
    }
  } catch (e) { console.warn('initDb:', e.message); }
}



/* ── STATIC + SPA ─────────────────────────────────────── */
app.use(express.static(join(__dirname, 'dist')));
app.get('*', (req, res) => {
  if (req.path.startsWith('/api')) return res.status(404).json({ error: 'Not found' });
  res.sendFile(join(__dirname, 'dist', 'index.html'));
});

app.listen(PORT, async () => { console.log('FLW Dashboard running on port', PORT); await initDb(); });
