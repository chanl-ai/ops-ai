"""Test plugins for the manifest fields a system needs: headers, a form body and an amount limit
(fields_desk), the client sent as basic auth on the token call (fields_zoom), and sign-in parameters with a lookup after
sign-in (fields_sites). uc-584 loads them through OPS_PLUGIN_PATHS against docs/usecases/lib/fake_multi_auth.py, and
test_plugin_manifest_fields.py runs them through the registry and the executors."""
