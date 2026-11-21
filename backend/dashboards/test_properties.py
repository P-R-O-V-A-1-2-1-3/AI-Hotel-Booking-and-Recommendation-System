import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from hotels.management.commands.import_osm_hotels import listing_from_element, name_key
from hotels.models import Hotel, HotelClaim

User = get_user_model()
MEDIA = tempfile.mkdtemp()


def png(name='room.png', size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, (20, 120, 90)).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA)
class OwnerListingLifecycleTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        res = self.client.post('/api/auth/register/', {
            'email': 'owner@example.com', 'password': 'S3cure-pass-77', 'firstName': 'Rupa', 'accountType': 'owner',
        }, format='json')
        self.assertEqual(res.data['user']['role'], 'owner')
        self.owner = User.objects.get(email='owner@example.com')
        self.admin = User.objects.create_user(email='admin@example.com', password='S3cure-pass-77', role='admin')
        self.client.force_authenticate(self.owner)

    def test_cannot_self_register_as_admin(self):
        self.client.force_authenticate(None)
        res = self.client.post('/api/auth/register/', {'email': 'x@example.com', 'password': 'S3cure-pass-77',
                                                        'firstName': 'X', 'accountType': 'admin'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_draft_to_live(self):
        # 1. Create a draft: private, not bookable
        res = self.client.post('/api/owner/hotels/', {
            'name': 'Hill Breeze Resort', 'city': 'Bandarban', 'location': 'Chimbuk Road',
            'amenities': ['Mountain view', 'mountain view', 'Free Wi-Fi'], 'latitude': 22.19, 'longitude': 92.21,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        hotel_id = res.data['id']
        self.assertEqual(res.data['approvalStatus'], 'draft')
        self.assertEqual(res.data['amenities'], ['Mountain view', 'Free Wi-Fi'])  # de-duplicated
        self.assertEqual(self.client.get(f'/api/hotels/{hotel_id}/').status_code, 404)

        # 2. Submitting an incomplete listing says what's missing
        res = self.client.post(f'/api/owner/hotels/{hotel_id}/submit/')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.data['missing']), {'description', 'rooms', 'photos'})

        # 3. Fill it in: description, a room, a photo (a fake image is rejected)
        self.client.patch(f'/api/owner/hotels/{hotel_id}/', {
            'description': 'Quiet hilltop cottages with sunrise views over the Bandarban ranges.'}, format='json')
        res = self.client.post(f'/api/owner/hotels/{hotel_id}/rooms/', {
            'name': 'Hill View Cottage', 'pricePerNight': 4800, 'originalPrice': 5600, 'capacity': 2, 'totalUnits': 3,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        bad = SimpleUploadedFile('fake.jpg', b'not really an image', content_type='image/jpeg')
        self.assertEqual(self.client.post(f'/api/owner/hotels/{hotel_id}/photos/', {'photos': [bad]}).status_code, 400)
        res = self.client.post(f'/api/owner/hotels/{hotel_id}/photos/', {'photos': [png(), png('front.png')]})
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(len(res.data['photos']), 2)
        self.assertEqual(res.data['pricePerNight'], 4800)  # listing price follows the cheapest room

        # 4. Submit → admin rejects with a note → owner fixes and resubmits → admin approves
        self.assertEqual(self.client.post(f'/api/owner/hotels/{hotel_id}/submit/').data['approvalStatus'], 'pending')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/admin/hotels/{hotel_id}/decision/', {'decision': 'reject'},
                                          format='json').status_code, 400)  # a note is required
        self.client.post(f'/api/admin/hotels/{hotel_id}/decision/', {'decision': 'reject', 'note': 'Add a phone number'},
                         format='json')
        self.client.force_authenticate(self.owner)
        mine = self.client.get(f'/api/owner/hotels/{hotel_id}/').data
        self.assertEqual((mine['approvalStatus'], mine['reviewNote']), ('rejected', 'Add a phone number'))
        self.client.patch(f'/api/owner/hotels/{hotel_id}/', {'phone': '+880 1711-000000'}, format='json')
        self.client.post(f'/api/owner/hotels/{hotel_id}/submit/')
        self.client.force_authenticate(self.admin)
        self.client.post(f'/api/admin/hotels/{hotel_id}/decision/', {'decision': 'approve'}, format='json')

        # 5. Live: public, bookable, cover photo is an absolute URL to the upload
        self.client.force_authenticate(None)
        public = self.client.get(f'/api/hotels/{hotel_id}/').data
        self.assertTrue(public['isBookable'])
        self.assertTrue(public['image'].startswith('http://testserver/media/hotels/'))
        self.assertEqual(public['rooms'][0]['name'], 'Hill View Cottage')

    def test_owners_cannot_touch_each_others_hotels(self):
        hotel = Hotel.objects.create(name='Mine', city='Dhaka', location='Gulshan', description='x', owner=self.owner)
        other = User.objects.create_user(email='other@example.com', password='S3cure-pass-77', role='owner')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.patch(f'/api/owner/hotels/{hotel.pk}/', {'name': 'Stolen'}, format='json').status_code, 404)
        self.assertEqual(self.client.post(f'/api/owner/hotels/{hotel.pk}/photos/', {'photos': [png()]}).status_code, 404)
        traveler = User.objects.create_user(email='t@example.com', password='S3cure-pass-77')
        self.client.force_authenticate(traveler)
        self.assertEqual(self.client.get('/api/owner/hotels/').status_code, 403)

    def test_claim_imported_listing(self):
        listing = Hotel.objects.create(name='Sea Breeze Inn', city="Cox's Bazar", location='Kolatoli', description='x',
                                       source=Hotel.Source.OSM, external_id='osm:node/1', latitude=21.43, longitude=92.0)
        public = self.client.get(f'/api/hotels/{listing.pk}/').data
        self.assertEqual((public['isBookable'], public['isClaimable'], public['pricePerNight']), (False, True, None))
        self.assertEqual([h['name'] for h in self.client.get('/api/owner/claimable/?search=breeze').data], ['Sea Breeze Inn'])

        claim = self.client.post('/api/owner/claims/', {'hotelId': listing.pk, 'message': 'I am the manager'}, format='json')
        self.assertEqual(claim.status_code, 201)
        self.assertEqual(self.client.post('/api/owner/claims/', {'hotelId': listing.pk}, format='json').status_code, 400)

        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/admin/claims/{claim.data['id']}/decision/", {'decision': 'approve'}, format='json')
        listing.refresh_from_db()
        self.assertEqual(listing.owner, self.owner)
        self.assertEqual(HotelClaim.objects.get().status, 'approved')

        # Now it's the owner's: they can add rooms, and it's no longer claimable
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(f'/api/owner/hotels/{listing.pk}/rooms/', {'name': 'Double', 'pricePerNight': 3000},
                                          format='json').status_code, 201)
        self.assertFalse(self.client.get(f'/api/hotels/{listing.pk}/').data['isClaimable'])


class OsmParsingTests(APITestCase):
    def test_listing_from_element(self):
        item = listing_from_element({
            'type': 'way', 'id': 42, 'center': {'lat': 21.4300, 'lon': 92.0050},
            'tags': {'name': 'Hotel Ocean View', 'tourism': 'hotel', 'stars': '3', 'internet_access': 'wlan',
                     'addr:street': 'Kolatoli Road', 'website': 'ftp://bad'},
        })
        self.assertEqual(item['external_id'], 'osm:way/42')
        self.assertEqual(item['city'], "Cox's Bazar")          # nearest town from coordinates
        self.assertEqual(item['location'], "Kolatoli Road, Cox's Bazar")
        self.assertEqual((item['stars'], item['amenities'], item['website']), (3, ['Wi-Fi'], ''))
        self.assertIsNone(listing_from_element({'type': 'node', 'id': 1, 'lat': 23.8, 'lon': 90.4, 'tags': {}}))

    def test_name_key_ignores_generic_words(self):
        self.assertEqual(name_key('Hotel Sea Pearl & Spa Ltd.'), name_key('Sea Pearl Resort'))
