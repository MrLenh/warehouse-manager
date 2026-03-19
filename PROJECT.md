# Warehouse Manager - Project Structure & Data

## Overview
Full-stack inventory management and order fulfillment system built with **FastAPI** (Python) + **HTML/JavaScript** frontend. Integrates with EasyPost for shipping.

---

## Directory Structure

```
warehouse-manager/
├── Dockerfile
├── docker-compose.yml
├── railway.toml
├── requirements.txt
├── .env.example
│
└── app/
    ├── main.py                          # FastAPI entry point
    ├── config.py                        # Configuration settings
    ├── database.py                      # SQLAlchemy setup & migrations
    │
    ├── models/
    │   ├── product.py                   # Product & Variant
    │   ├── order.py                     # Order & OrderItem
    │   ├── customer.py                  # Customer
    │   ├── user.py                      # User & ActivityLog
    │   ├── invoice.py                   # Invoice
    │   ├── picking.py                   # PickingList & PickItem
    │   ├── stock_request.py             # StockRequest, StockRequestItem, StockRequestBox
    │   ├── stock_batch.py               # StockBatch (FIFO tracking)
    │   └── inventory_log.py             # InventoryLog (audit trail)
    │
    ├── schemas/
    │   ├── product.py
    │   ├── order.py
    │   ├── customer.py
    │   ├── invoice.py
    │   ├── picking.py
    │   └── stock_request.py
    │
    ├── api/
    │   ├── auth.py                      # Authentication & user management
    │   ├── products.py                  # Product CRUD, variants, inventory
    │   ├── orders.py                    # Order CRUD, import/export, shipping
    │   ├── picking.py                   # Picking lists & QR scanning
    │   ├── customers.py                 # Customer & invoice management
    │   ├── stock_requests.py            # Stock request management
    │   ├── portal.py                    # Customer portal (read-only)
    │   ├── reports.py                   # Analytics & reporting
    │   ├── webhooks.py                  # EasyPost & custom webhooks
    │   └── jobs.py                      # Background jobs
    │
    ├── services/
    │   ├── auth_service.py              # JWT, password hashing, user mgmt
    │   ├── product_service.py           # Product/variant business logic
    │   ├── order_service.py             # Order creation & status workflows
    │   ├── picking_service.py           # Picking list generation & scanning
    │   ├── stock_request_service.py     # Stock request workflows
    │   ├── shipping_service.py          # EasyPost integration
    │   ├── webhook_service.py           # Webhook event dispatching
    │   ├── report_service.py            # Analytics & reporting logic
    │   ├── tracking_service.py          # Order tracking updates
    │   ├── qr_service.py               # QR code generation
    │   └── scheduler_service.py         # APScheduler background tasks
    │
    └── static/
        ├── login.html                   # Login page
        ├── index.html                   # Main dashboard/inventory
        ├── product.html                 # Product detail
        ├── customer.html                # Customer & invoice management
        ├── picking.html                 # Mobile picking list
        ├── packing.html                 # Packing station
        └── portal.html                  # Customer portal
```

---

## Data Models

### Product
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| sku | String | Unique SKU (indexed) |
| name, description, category | String | Product info |
| weight_oz, length_in, width_in, height_in | Float | Dimensions |
| price | Float | Unit price |
| quantity | Integer | Current stock |
| location | String | Warehouse location code |
| qr_code_path | String | Path to QR code |
| image_url, image_data, image_content_type | String/Binary | Image storage |
| option_types | JSON | Variant option names |
| customer_id | UUID FK | Multi-tenant support |
| created_at, updated_at | DateTime | Timestamps |

### Variant
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| product_id | UUID FK | Parent product |
| variant_sku | String | Unique variant SKU |
| attributes | JSON | e.g. `{"color":"Red","size":"M"}` |
| price_override, weight_oz_override, etc. | Float | Override parent values |
| quantity | Integer | Variant stock |
| location | String | Variant warehouse location |

### Order
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| order_number | String | Unique, auto-generated |
| order_name | String | User-friendly name |
| customer_name, customer_id, customer_email, customer_phone | String/UUID | Customer info |
| shop_name | String | Store/shop identifier |
| ship_to_* | String | Shipping address fields |
| ship_from_* | String | Return address fields |
| status | Enum | pending, confirmed, processing, packing, packed, label_purchased, drop_off, shipped, in_transit, delivered, on_hold, cancelled |
| priority | Enum | low, normal, high, urgent |
| status_history | JSON | Status changes with timestamps |
| shipping_cost, processing_fee, total_price | Float | Pricing |
| carrier, service | String | Shipping carrier & service |
| easypost_shipment_id, tracking_number, tracking_url, label_url | String | EasyPost integration |
| invoice_id | UUID FK | Optional invoice |

### OrderItem
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| order_id | UUID FK | Parent order |
| product_id | UUID FK | Product reference |
| variant_id | UUID | Variant ID (optional) |
| sku, variant_sku, variant_label | String | SKU info |
| name, product_name | String | Display names |
| quantity | Integer | Quantity ordered |
| unit_price | Float | Price per unit |

### Customer
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| name | String | Customer name |
| email, phone, company | String | Contact info |
| webhook_url | String | Custom webhook endpoint |
| webhook_payload_fields | JSON | Fields to include in webhook |

### User
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| username | String | Unique (indexed) |
| display_name | String | Display name |
| password_hash | String | Bcrypt hash |
| role | Enum | super_admin, admin, staff, customer |
| active | Boolean | Account status |
| customer_id | UUID FK | For customer-role users |

### Invoice
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| invoice_number | String | Unique invoice number |
| customer_id | UUID FK | Customer |
| date_to | Date | Invoice period end |
| status | Enum | new, requested, paid, cancel |
| processing_fee_unit/total, shipping_fee_total, stocking_fee_unit/total | Float | Fee breakdown |
| discount, total_price | Float | Totals |

### PickingList
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| picking_number | String | Unique number |
| status | Enum | active, processing, done, archived |
| priority | Enum | low, normal, high, urgent |
| assigned_to | String | Assigned picker |

### PickItem
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| picking_list_id | UUID FK | Parent list |
| order_id, order_item_id, product_id | UUID FK | References |
| sku, product_name, variant_label | String | Display info |
| sequence | Integer | Unit number (1-based) |
| qr_code | String | Unique QR identifier |
| picked | Boolean | Completion status |
| picked_at | DateTime | When picked |

### StockRequest
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| request_number | String | Unique number |
| supplier, ship_from | String | Supplier info |
| status | Enum | draft, pending, approved, receiving, completed, cancelled |
| tracking_id, carrier | String | Inbound tracking |

### StockRequestItem
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| stock_request_id, product_id, variant_id | UUID FK | References |
| quantity_requested, quantity_received | Integer | Quantities |
| unit_cost | Float | Cost per unit |
| box_count | Integer | Number of boxes |

### StockBatch (FIFO Costing)
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| product_id, variant_id, stock_request_id | UUID FK | References |
| unit_cost | Float | Cost per unit |
| quantity_received, quantity_remaining | Integer | Tracking |

### InventoryLog (Audit Trail)
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| product_id | UUID FK | Product |
| change | Integer | Quantity change (+/-) |
| reason | Enum | inbound, order, adjustment |
| reference_id | String | Related order/request ID |
| balance_after | Integer | Balance after change |
| gap | Integer | In-warehouse adjustment delta |

---

## API Endpoints

### Auth — `/api/v1/auth`
- `POST /login` — Login (returns JWT cookie)
- `POST /logout` — Clear session
- `GET /me` — Current user info
- `GET /users` — List users (admin)
- `POST /users` — Create user (admin)
- `PATCH /users/{id}` — Update user
- `PATCH /users/{id}/active` — Toggle active
- `POST /users/{id}/reset-password` — Reset password
- `POST /change-password` — Change own password
- `GET /activity` — Activity logs

### Products — `/api/v1/products`
- `POST /` — Create product
- `GET /` — List products (filter by category)
- `GET /low-stock` — Low stock products
- `GET /export` — Export CSV
- `POST /import` — Import CSV
- `GET /{id}` — Get product
- `PATCH /{id}` — Update product
- `POST /{id}/inventory` — Adjust inventory
- `GET /{id}/inventory-logs` — Audit trail
- `POST /{id}/generate-qr` — Generate QR
- `GET /{id}/qrcode` — Get QR label (PNG)
- `GET /{id}/qrcode/bulk` — Printable PDF with QR labels
- Variants: `POST /{id}/variants`, `GET /{id}/variants`, `PATCH /variants/{id}`, `DELETE /variants/{id}`

### Orders — `/api/v1/orders`
- `POST /` — Create order
- `GET /` — List orders (filter: status, search, SKU, priority)
- `GET /export` — Export CSV
- `POST /import` — Import CSV
- `POST /merge-by-name` — Merge orders with same name
- `GET /{id}` — Get order
- `PATCH /{id}` — Update order
- `PATCH /{id}/status` — Update status
- `POST /{id}/cancel` — Cancel order
- `POST /{id}/buy-label` — Purchase shipping label (EasyPost)
- `GET /{id}/rates` — Get shipping rates
- `DELETE /{id}` — Delete (admin only)

### Picking Lists — `/api/v1/picking-lists`
- `POST /` — Create picking list from orders
- `GET /` — List picking lists
- `GET /{id}` — Get list details
- `GET /{id}/progress` — Progress (picked/total)
- `POST /scan` — Scan QR (mark item picked)
- `POST /label-batch` — Create batch from label_purchased orders

### Stock Requests — `/api/v1/stock-requests`
- `POST /` — Create request (draft)
- `GET /` — List requests
- `GET /{id}` — Get request
- `POST /{id}/approve` — Approve
- `POST /{id}/receive` — Receive items
- `POST /{id}/complete` — Complete
- `POST /{id}/cancel` — Cancel
- `POST /{id}/scan-box` — Scan box barcode

### Customers — `/api/v1/customers`
- CRUD: `POST /`, `GET /`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`
- Invoices: `GET /{id}/invoices`, `POST /{id}/invoices`, `GET /invoices/{id}`, `PATCH /invoices/{id}`, `PATCH /invoices/{id}/status`

### Portal — `/api/v1/portal`
- `GET /dashboard` — Customer dashboard
- `GET /orders`, `/invoices`, `/inventory`, `/products` — Customer data
- `POST /stock-request` — Submit stock request

### Reports — `/api/v1/reports`
- `GET /inventory` — Inventory summary
- `GET /orders` — Order summary
- `GET /top-products` — Top products by sales
- `GET /inventory-overview` — By status
- `GET /inventory-daily` — Daily totals
- `GET /inventory-daily-chart` — Chart data
- `GET /inventory-movement` — Change audit

---

## Key Workflows

### Order Processing
```
confirmed → processing → packing → packed → label_purchased → drop_off → shipped → in_transit → delivered
                                                                                   ↗
                                                              on_hold (pause) ──────
                                                              cancelled (rollback inventory)
```

### Stock Request
```
draft → pending → approved → receiving → completed
                                       → cancelled
```

### Picking & Packing
1. Create picking list from orders → generates PickItems with QR codes
2. Scanner app scans QR → marks items picked
3. When all items picked → picking list marked done
4. Packing station verifies & prepares for shipping

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI 0.115 (Python 3.12) |
| Database | SQLAlchemy 2.0 + SQLite (dev) / PostgreSQL (prod) |
| Auth | JWT (PyJWT) + bcrypt |
| Shipping | EasyPost API |
| Frontend | HTML5 + vanilla JavaScript |
| QR Codes | python-barcode + Pillow |
| Background Jobs | APScheduler |
| HTTP Client | httpx |
| Deployment | Docker + Railway |

---

## Configuration

Environment variables (`.env`):
- `DATABASE_URL` — DB connection string
- `EASYPOST_API_KEY` — Shipping API key
- `SECRET_KEY` — JWT secret
- `PROCESSING_FEE_FIRST_ITEM` / `PROCESSING_FEE_EXTRA_ITEM` — Fulfillment fees
- `STOCKING_FEE_PER_ITEM` — Storage fee
- `WAREHOUSE_*` — Return address fields
- `WEBHOOK_URLS` / `WEBHOOK_SECRET` — Webhook config
