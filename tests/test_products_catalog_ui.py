import unittest
from app import create_app
from database import db
from models import Organization, User, Product, Membership


class TestProductsCatalogUIAndAPI(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Set up default test organization
        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="OpsFlow Cloud Test Corp",
                slug="opsflow-test-corp",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        # Set up admin user
        self.user = User.query.filter_by(email="catalog_admin@opsflow.io").first()
        if not self.user:
            self.user = User(
                id="usr-catalog-admin",
                email="catalog_admin@opsflow.io",
                full_name="Catalog Admin",
                is_active=True
            )
            self.user.set_password("AdminPass123!")
            db.session.add(self.user)
            db.session.commit()

            mem = Membership(
                id="mem-catalog-admin",
                user_id=self.user.id,
                organization_id=self.org.id,
                role="admin"
            )
            db.session.add(mem)
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_frontend_index_html_contains_products_catalog_tab_and_modals(self):
        """Verifies that the dashboard frontend includes the Products Catalog tab, table, and modals."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 1. Sidebar tab navigation button
        self.assertIn("switchTab('products')", html)
        self.assertIn("Products Catalog", html)

        # 2. Main Tab Section
        self.assertIn('id="tab-products"', html)
        self.assertIn("PRODUCTS CATALOG &amp; ONLINE SHOP", html)
        self.assertIn('id="productsTable"', html)
        self.assertIn('id="productsTableBody"', html)
        self.assertIn('id="productGridViewContainer"', html)

        # 3. KPI stat counters
        self.assertIn('id="prodMetricTotal"', html)
        self.assertIn('id="prodMetricInStock"', html)
        self.assertIn('id="prodMetricLowStock"', html)
        self.assertIn('id="prodMetricOutOfStock"', html)
        self.assertIn('id="prodMetricValuation"', html)

        # 4. Modals
        self.assertIn('id="modalAddProduct"', html)
        self.assertIn('id="modalEditProduct"', html)
        self.assertIn('id="modalShareCatalog"', html)
        self.assertIn('id="modalProductImagePreview"', html)

        # 5. Add Product Form Fields
        self.assertIn('id="addProdName"', html)
        self.assertIn('id="addProdPrice"', html)
        self.assertIn('id="addProdStock"', html)
        self.assertIn('id="addProdImageUrl"', html)

    def test_products_catalog_api_lifecycle(self):
        """Verifies end-to-end CRUD for online store products via the REST API."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        # 1. Seed demo products
        seed_resp = self.client.post("/api/v1/ecommerce/products/seed-demo")
        self.assertEqual(seed_resp.status_code, 201)
        seed_data = seed_resp.get_json()
        self.assertEqual(seed_data["status"], "success")

        # 2. Query product list
        list_resp = self.client.get("/api/v1/ecommerce/products?include_inactive=true")
        self.assertEqual(list_resp.status_code, 200)
        list_data = list_resp.get_json()
        self.assertGreaterEqual(list_data["count"], 1)
        self.assertIn("stats", list_data)
        self.assertGreater(list_data["stats"]["total"], 0)

        # 3. Create a custom product
        create_resp = self.client.post("/api/v1/ecommerce/products", json={
            "name": "OpsFlow Wireless Mechanical Keyboard",
            "category": "Gaming",
            "description": "Hot-swappable RGB mechanical keyboard",
            "sku": "KB-OPS-99",
            "barcode": "890987654321",
            "image_url": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500",
            "unit": "piece",
            "price": 8500.0,
            "currency": "PKR",
            "stock_quantity": 15,
            "is_active": True
        })
        self.assertEqual(create_resp.status_code, 201)
        new_prod = create_resp.get_json()["product"]
        prod_id = new_prod["id"]
        self.assertEqual(new_prod["name"], "OpsFlow Wireless Mechanical Keyboard")
        self.assertEqual(new_prod["price"], 8500.0)
        self.assertEqual(new_prod["stock_quantity"], 15)
        self.assertEqual(new_prod["image_url"], "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500")

        # 4. Retrieve single product
        get_resp = self.client.get(f"/api/v1/ecommerce/products/{prod_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.get_json()["product"]["sku"], "KB-OPS-99")

        # 5. Update product price and stock
        upd_resp = self.client.put(f"/api/v1/ecommerce/products/{prod_id}", json={
            "price": 7999.0,
            "stock_quantity": 8,
            "image_url": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=600"
        })
        self.assertEqual(upd_resp.status_code, 200)
        updated = upd_resp.get_json()["product"]
        self.assertEqual(updated["price"], 7999.0)
        self.assertEqual(updated["stock_quantity"], 8)
        self.assertEqual(updated["image_url"], "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=600")

        # 6. Delete product
        del_resp = self.client.delete(f"/api/v1/ecommerce/products/{prod_id}")
        self.assertEqual(del_resp.status_code, 200)
        del_data = del_resp.get_json()
        self.assertEqual(del_data["status"], "success")


if __name__ == "__main__":
    unittest.main()
