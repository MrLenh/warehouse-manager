# FLW Shopify Dashboard

Full-stack analytics dashboard for FLW (Flagwix) Shopify data. Built with React/Vite + Node.js/Express + MySQL.

## Quick Start

### 1. Install
```bash
npm install
```

### 2. Configure .env
```env
DB_HOST=
DB_PORT=
DB_USER=your-db-user
DB_PASSWORD=your-db-password
DB_NAME=flw_shopify
DB_SSL=false
JWT_SECRET=your-random-32-byte-hex-string
ADMIN_EMAIL=
ADMIN_PASSWORD=your-secure-password
PORT=3001
```

### 3. Dev mode (frontend + backend concurrently)
```bash
npm run dev
```
- Frontend: http://localhost:5173
- Backend API: http://localhost:3001

### 4. Production build
```bash
npm run build
npm start
```

## Deploy to Railway
1. Push repo to GitHub
2. New project → Deploy from repo
3. Set environment variables in Railway dashboard
4. Railway auto-detects nixpacks.toml

## Pages
1. **Executive Overview** — KPIs, P&L, trend chart, revenue by store, AI insights
2. **Daily Performance** — Dual-column cards (current vs compare period), Product detail table
3. **Orders** — 4 search boxes, column chooser, Export order/line item buttons
4. **Products** — Catalog with thumbnail, tags, categories
5. **Product Report** — SKU-level: Orders/Qty/Subtotal/Cogs/GG Ads/Tags
6. **Shop Comparison** — Side-by-side multi-store metrics + trend chart
7. **Platform Report** — Daily by Website × Platform with full P&L columns
8. **Facebook Ads** — Multi-account filter, campaign expand (+), KPI bar
9. **Google Ads** — Summary tab (campaign) + Product tab (SKU-level)
10. **Profit Analytics** — Waterfall chart, margin trend, full P&L
11. **Customers** — US state bar chart, country breakdown, LTV
12. **Refunds & Coupons** — Refund trend, coupon usage table
13. **Operations** — Order status pie, shipping method breakdown

## Auth
On first run, the server creates a `flw_users` table in your MySQL DB and creates the admin user from `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars.

## Notes
- Query cache: 2-minute TTL for SELECT queries
- MySQL pool: 20 connections
- JWT: 7-day token expiry
- Dark mode toggle in sidebar
