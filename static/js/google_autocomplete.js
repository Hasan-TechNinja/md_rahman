console.log("google_autocomplete.js loaded");
window.addEventListener('load', function () {

  console.log('Google object:', window.google);

  const input = document.querySelector('.google-places-autocomplete');

  if (!input) {
    console.log('Location search input not found');
    return;
  }

  if (!window.google || !google.maps || !google.maps.places) {
    console.error('Google Places API not loaded');
    return;
  }

  const autocomplete = new google.maps.places.Autocomplete(input);

  autocomplete.addListener('place_changed', function () {
  const place = autocomplete.getPlace();

  if (!place.geometry) {
    return;
  }

  const lat = place.geometry.location.lat();
  const lng = place.geometry.location.lng();


  document.getElementById('id_location_map').value =
    `${lat},${lng}`;

  console.log("Place selected", place);
  console.log("Place ID", place.place_id);

  const service = new google.maps.places.PlacesService(
    document.createElement('div')
  );


service.getDetails(
  {
    placeId: place.place_id,
    fields: ['rating']
  },
  function(details, status) {

    console.log("Details callback fired");
    console.log("Status:", status);
    console.log("Details:", details);

    if (
      status === google.maps.places.PlacesServiceStatus.OK &&
      details.rating
    ) {
      console.log("Google Rating:", details.rating);
      document.getElementById('id_google_rating').value=details.rating
    }
  }
);
});

  console.log('Places autocomplete initialized');
});