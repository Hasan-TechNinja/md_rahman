import requests

from laundrymart import settings
import logging
logger = logging.getLogger(__name__)


def reverse_geocode_google(lat: float, lng: float) -> dict | None:
  """
  Call Google Reverse Geocoding API and try to extract structured address
  Returns format like your example or None if failed
  """
  logger.info('reverse triggered')
  if not settings.GOOGLE_MAP_API_KEY:  # assuming you have GOOGLE_MAP_API_KEY = os.getenv('GOOGLE_MAP_API')
    return None

  url = "https://maps.googleapis.com/maps/api/geocode/json"
  params = {
    "latlng": f"{lat},{lng}",
    "key": settings.GOOGLE_MAP_API_KEY,
    "language": "en",  # or your preferred language
    "result_type": "street_address|premise|route",  # prefer precise results (optional)
  }
  logger.info(params)

  try:
    response = requests.get(url, params=params, timeout=8)
    logger.info(response)
    data = response.json()
    logger.info(data)

    if data.get("status") != "OK" or not data.get("results"):
      return None

    # Take the most relevant (usually first) result
    result = data["results"][0]
    components = result.get("address_components", [])

    address = {
      "street_address": [],
      "city": "",
      "state": "",
      "zip_code": "",
      "country": ""
    }

    street_parts = []

    for comp in components:
      types = comp.get("types", [])

      if "street_number" in types:
        street_parts.insert(0, comp["long_name"])
      elif "route" in types:
        street_parts.append(comp["long_name"])
      elif any(t in types for t in ["locality", "sublocality"]):
        address["city"] = comp["long_name"]
      elif "administrative_area_level_1" in types:
        address["state"] = comp["short_name"]  # usually state code (NJ)
      elif "postal_code" in types:
        address["zip_code"] = comp["long_name"]
      elif "country" in types:
        address["country"] = comp["short_name"]  # ISO code "US"

    # Combine house number + street name
    if street_parts:
      address["street_address"] = street_parts  # already list like ["8", "Furler Street"]

    # If street_address is still empty but we have premise/route, fallback
    if not address["street_address"] and "premise" in result.get("types", []):
      address["street_address"] = [result["formatted_address"].split(",")[0].strip()]

    # Only return if we have at least city + country or similar
    if address["city"] or address["country"]:
      return address
    return None

  except Exception as e:
    # log error in production
    logger.error(f"Reverse geocoding failed: {e}")
    return None