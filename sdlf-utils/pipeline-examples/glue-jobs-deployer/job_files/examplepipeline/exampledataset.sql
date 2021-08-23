SELECT countrycodes.country_code,
       countrynames.country_code
FROM $SOURCE_DATABASE.countrycodes
LEFT JOIN $SOURCE_DATABASE_1.countrynames