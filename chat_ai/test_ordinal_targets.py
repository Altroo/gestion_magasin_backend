from datetime import timedelta
from django.test import SimpleTestCase
from django.utils import timezone
from .targets import trusted_target


class OrdinalTargetTests(SimpleTestCase):
    def test_ordinal_precedes_current_page_and_saved_membership(self):
        now = timezone.now()
        resource, noun = ('product', 'product')
        state = {"resource": resource, "ids": [311, 8092, 1456],
                 "expires_at": (now + timedelta(minutes=5)).isoformat()}
        kwargs = dict(instruction=f"Update the third {noun}.", state=state,
                      context={"resource":resource,"identifier":311}, now=now)
        self.assertFalse(trusted_target(resource,311,**kwargs))
        self.assertTrue(trusted_target(resource,1456,**kwargs))
        for expired in [{}, {**state,"expires_at":now.isoformat()}]:
            self.assertFalse(trusted_target(resource,311,**{**kwargs,"state":expired}))

    def test_quote_does_not_override_explicit_native_id(self):
        resource,noun = ('product', 'product')
        self.assertTrue(trusted_target(resource,311,instruction=f'Update {noun} ID 311: name "The third {noun}".',
                                       state={},context={},now=timezone.now()))
