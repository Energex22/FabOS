class GlobalSearchService:
    def __init__(self,db):
        self.db=db

    def search(self,query,limit_per_type=8):
        q=(query or "").strip()
        if not q:return []
        like="%%%s%%"%q
        results=[]
        with self.db.connect() as c:
            def add(kind,page,sql,args):
                for row in c.execute(sql,args).fetchall():
                    results.append({
                        "kind":kind,"page":page,"id":row["id"],
                        "title":row["title"],"detail":row["detail"] or "",
                        "status":row["status"] or ""
                    })
            add("Product","Products","""SELECT id,name title,
                TRIM(COALESCE(sku,'')||CASE WHEN category<>'' THEN ' • '||category ELSE '' END) detail,
                COALESCE(license_status,'') status FROM products
                WHERE name LIKE ? OR COALESCE(sku,'') LIKE ? OR COALESCE(category,'') LIKE ?
                OR COALESCE(designer,'') LIKE ? ORDER BY name LIMIT ?""",
                (like,like,like,like,limit_per_type))
            add("Print File","Products","""SELECT p.id,a.original_name title,
                p.name||' • '||a.kind detail,a.kind status
                FROM design_assets a JOIN designs d ON d.id=a.design_id
                JOIN products p ON p.id=d.product_id
                WHERE a.original_name LIKE ? OR p.name LIKE ? OR a.kind LIKE ?
                ORDER BY a.created_at DESC LIMIT ?""",
                (like,like,like,limit_per_type))
            add("Customer","Customers","""SELECT id,name title,
                TRIM(COALESCE(email,'')||CASE WHEN phone<>'' THEN ' • '||phone ELSE '' END) detail,
                '' status FROM customers WHERE name LIKE ? OR COALESCE(email,'') LIKE ?
                OR COALESCE(phone,'') LIKE ? ORDER BY name LIMIT ?""",
                (like,like,like,limit_per_type))
            add("Quote","Quotes","""SELECT q.id,q.quote_number title,COALESCE(c.name,'No customer') detail,
                q.status FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id
                WHERE q.quote_number LIKE ? OR COALESCE(c.name,'') LIKE ? OR COALESCE(q.notes,'') LIKE ?
                ORDER BY q.created_at DESC LIMIT ?""",(like,like,like,limit_per_type))
            add("Order","Orders","""SELECT o.id,o.order_number title,COALESCE(c.name,'No customer') detail,
                o.status FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
                WHERE o.order_number LIKE ? OR COALESCE(c.name,'') LIKE ?
                ORDER BY o.created_at DESC LIMIT ?""",(like,like,limit_per_type))
            add("Invoice","Invoices","""SELECT i.id,i.invoice_number title,
                COALESCE(c.name,'No customer')||' • $'||printf('%.2f',i.total_cents/100.0) detail,
                i.status FROM invoices i LEFT JOIN orders o ON o.id=i.order_id
                LEFT JOIN customers c ON c.id=o.customer_id
                WHERE i.invoice_number LIKE ? OR COALESCE(o.order_number,'') LIKE ?
                OR COALESCE(c.name,'') LIKE ? ORDER BY i.created_at DESC LIMIT ?""",
                (like,like,like,limit_per_type))
            add("Print Job","Production","""SELECT j.id,substr(j.id,1,8) title,
                COALESCE(p.name,'Custom Job')||CASE WHEN pr.name IS NOT NULL THEN ' • '||pr.name ELSE '' END detail,
                j.status FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id
                LEFT JOIN printers pr ON pr.id=j.printer_id
                WHERE j.id LIKE ? OR COALESCE(p.name,'') LIKE ? OR COALESCE(pr.name,'') LIKE ?
                ORDER BY j.created_at DESC LIMIT ?""",(like,like,like,limit_per_type))
            add("Printer","Printers","""SELECT id,name title,COALESCE(model,'Printer') detail,
                COALESCE(status,'') status FROM printers
                WHERE name LIKE ? OR COALESCE(model,'') LIKE ? ORDER BY name LIMIT ?""",
                (like,like,limit_per_type))
            add("Filament","Filament","""SELECT id,
                COALESCE(brand||' ','')||COALESCE(material,'Filament')||CASE WHEN color<>'' THEN ' • '||color ELSE '' END title,
                printf('%.0f g remaining',remaining_g) detail,
                CASE WHEN active=1 THEN 'active' ELSE 'inactive' END status FROM filament_spools
                WHERE COALESCE(brand,'') LIKE ? OR COALESCE(material,'') LIKE ? OR COALESCE(color,'') LIKE ?
                ORDER BY remaining_g LIMIT ?""",(like,like,like,limit_per_type))
        return results
