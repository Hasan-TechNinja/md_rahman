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

    console.log(place);
  });

  console.log('Places autocomplete initialized');
});

