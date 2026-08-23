# FabOS Alpha 0.9.0 — Inventory & Profitability

## Filament Inventory
- Functional Filament page with sortable spool table.
- Add spools with material, brand, color, weight, price, location and lot.
- Manual remaining-weight adjustment with transaction history.
- Cost per gram calculated from actual spool purchase cost.
- 30-day usage shown per spool.
- Low-stock and projected run-out recommendations.
- User-adjustable low threshold and forecast window.

## Automatic Consumption
- Successful completed jobs deduct the assigned spool once.
- Every automatic consumption is recorded as an inventory transaction.
- Duplicate completion processing cannot consume the same job twice.

## Costing
- Material cost uses the actual assigned spool's cost per gram.
- Machine cost uses actual/estimated job duration and configurable hourly cost.
- Packaging cost is configurable.
- Each completed print receives tracked cost and profit values.

## Analytics
- New Analytics page.
- Product-level job count, completed prints, tracked costs, tracked profit and average print time.
- Summary cards for completed jobs, tracked costs and tracked profit.

This is an operational-cost model, not tax/accounting software. Shipping fees, taxes,
marketplace fees and labor can be added to the costing model in a later commerce release.
