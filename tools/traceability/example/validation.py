# @artifact VER-DEVICE-IDENTITY type=verification
# @verifies REQ-DEVICE-IDENTITY
class DeviceIdentityVerification:
    # identity-read @verifies SPEC-DEVICE#identity-register coverage=complete
    def test_identity_read(self):
        """La lectura tras reset devuelve la firma y versión esperadas."""
