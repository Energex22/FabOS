import unittest

from fabos_core.api import _public_product


class FakeProducts:
    def images(self, product_id):
        return [{
            "id": "image-1",
            "path": "/private/server/path/secret.jpg",
            "is_primary": 1,
            "alt_text": "Product preview",
        }]

    def variants(self, product_id):
        return []


class FakeApplication:
    products = FakeProducts()


class CustomerApiSecurityTests(unittest.TestCase):
    def test_public_product_does_not_expose_server_image_path(self):
        row = {
            "id": "product-1",
            "sku": "FAB-001",
            "name": "Example",
            "description": "Example product",
            "category": "Test",
            "subcategory": "",
            "active": 1,
            "price_cents": 2000,
        }
        payload = _public_product(row, FakeApplication())
        image = payload["images"][0]
        self.assertNotIn("path", image)
        self.assertEqual(image["url"], "/api/v1/catalog/product-1/images/image-1")
        self.assertNotIn("secret.jpg", str(payload))


if __name__ == "__main__":
    unittest.main()
