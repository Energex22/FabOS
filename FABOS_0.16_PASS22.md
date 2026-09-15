# FabOS 0.16 — Pass 22

## API read-boundary expansion

Pass 22 extends the Pass 21 transport boundary without adding a second business-logic layer.

Added protected API read routes for:

- products/catalog
- customers
- quotes

Customer accounts are restricted to their linked customer for customer and quote reads. Employee/administrator accounts retain the existing service-level read behavior after permission checks. Product catalog reads use the existing ProductService rather than direct database access from the transport layer.

Added service-level customer/quote scoped read methods so ownership rules remain reusable outside the API transport.

## Compatibility

No third-party API framework was added. The existing Python 3.8-compatible architecture and desktop workflow remain intact.

## Regression coverage

`tests/test_pass22_api_read_boundaries.py` covers protected catalog reads, customer isolation, quote isolation, and authentication requirements.

CI is triggered by the changes and must complete before this pass is considered verified.
