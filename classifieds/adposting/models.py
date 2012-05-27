"""
  $Id$
"""

from django.db import models
from django.contrib.sites.models import Site
from django.contrib.auth.models import User

# next four lines are for sending the payment email
from django.template import Context, loader
from django.utils.translation import ugettext as _
from django.core.mail import send_mail

from django.conf import settings

import datetime
from PIL import Image

class ImageFormat(models.Model):
  format = models.CharField(max_length=10)
  
  def __unicode__(self):
    return self.format

class Category(models.Model):
  site = models.ForeignKey(Site)
  template_prefix = models.CharField(max_length=200)
  name = models.CharField(max_length=200)
  enable_contact_form_upload = models.BooleanField()
  contact_form_upload_max_size = models.IntegerField()
  contact_form_upload_file_extensions = models.CharField(max_length=200)
  images_max_count = models.IntegerField()
  images_max_width = models.IntegerField(help_text='Maximum width in pixels.')
  images_max_height = models.IntegerField(help_text='Maximum height in pixels.')
  images_max_size = models.IntegerField(help_text='Maximum size in bytes.')
  images_allowed_formats = models.ManyToManyField(ImageFormat)
  description = models.TextField()
  sortby_fields = models.CharField(max_length=200, help_text='A comma separated list of field names that should show up as sorting options.', blank=True)
  
  def __unicode__(self):
    return self.name + u' Category'

  class Meta:
    verbose_name_plural = u'categories'

class Field(models.Model):
  BOOLEAN_FIELD = 1
  CHAR_FIELD = 2
  DATE_FIELD = 3
  DATETIME_FIELD = 4
  EMAIL_FIELD = 5
  FILE_FIELD = 6
  FLOAT_FIELD = 7
  IMAGE_FIELD = 8
  INTEGER_FIELD = 9
  TIME_FIELD = 10
  URL_FIELD = 11
  TEXT_FIELD = 12
  SELECT_FIELD = 13
  FIELD_CHOICES = (
   (BOOLEAN_FIELD, 'Checkbox'),
   (CHAR_FIELD, 'Text Input (one line)'),
   (DATE_FIELD, 'Date Selector'),
   (DATETIME_FIELD, 'Date and Time Selector'),
   (EMAIL_FIELD, 'Email Address'),
   (FILE_FIELD, 'File Upload'),
   (FLOAT_FIELD, 'Decimal Number'),
   (IMAGE_FIELD, 'Image Upload'),
   (INTEGER_FIELD, 'Integer Number'),
   (TIME_FIELD, 'Time Selector'),
   (URL_FIELD, 'URL Input'),
   (TEXT_FIELD, 'Text Input (multi-line)'),
   (SELECT_FIELD, 'Dropdown List of Options'),
  )
  category = models.ForeignKey(Category, null=True, blank=True)
  name = models.CharField(max_length=100)
  label = models.CharField(max_length=200)
  field_type = models.IntegerField(choices=FIELD_CHOICES)
  help_text = models.TextField(blank=True)
  max_length = models.IntegerField(null=True, blank=True)
  enable_counter = models.BooleanField(help_text='This enabled the javascript counter script for text fields.')
  enable_wysiwyg = models.BooleanField(help_text='This enables the text formatting javascript widget for text fields.')
  required = models.BooleanField()
  options = models.TextField(help_text='A comma separated list of options [only for the dropdown list field]', blank=True)

  def __unicode__(self):
    return self.name + u' field for ' + self.category.name

class Ad(models.Model):
  category = models.ForeignKey(Category)
  user = models.ForeignKey(User)
  created_on = models.DateTimeField(auto_now_add=True)
  expires_on = models.DateTimeField()
  active = models.BooleanField() # active means that the ad was actually created
  title = models.CharField(max_length=255)
  
  def __unicode__(self):
    return u'Ad #' + unicode(self.pk) + ' titled "' + self.title + u'" in category ' + self.category.name
    
  def expired(self):
    if self.expires_on <= datetime.datetime.now():
      return True
    else:
      return False
  
  def fields(self):
    fields_list = []
    fields = list(self.category.field_set.all())
    fields += list(Field.objects.filter(category=None))
      
    for field in fields:
      try:
        fields_list.append( (field, field.fieldvalue_set.get(ad=self),) )
      except FieldValue.DoesNotExist:
        pass
        
    return fields_list
  
  def fields_dict(self):
    fields_dict = {}
    for key, value in self.fields():
      fields_dict[key.name] = value.value
      
    return fields_dict
    
  def is_featured(self):
    for payment in self.payment_set.all():
      if payment.paid_on <= datetime.datetime.now() and \
         payment.paid_on + datetime.timedelta(days=payment.pricing.length) >= datetime.datetime.now():
        for option in payment.options.all():
          if option.name == PricingOptions.FEATURED_LISTING:
            return True
          
    return False
    
  
  def make_payment(self, payment):
    # update expires_on
    self.expires_on += datetime.timedelta(days=payment.pricing.length)
    self.created_on = datetime.datetime.now()
    self.active = True
    self.save()
    
    # send email for payment
    # 1. render context to email template
    email_template = loader.get_template('adposting/email/payment.txt')
    context = Context({'payment': payment})
    email_contents = email_template.render(context)
    # 2. send email
    send_mail(_('Your payment has been processed.'), email_contents, settings.FROM_EMAIL, [payment.ad.user.email], fail_silently=False)

import StringIO
from os.path import basename

class AdImage(models.Model):
  ad = models.ForeignKey(Ad)
  full_photo = models.ImageField(upload_to='uploads/', blank=True)
  thumb_photo = models.ImageField(upload_to='uploads/thumbnails/', blank=True)
  
  def generate_thumbnail(self):
    image = Image.open(self.full_photo.path)
    if image.mode != "RGB":
      image = image.convert('RGB')
    # resize
    image = image.resize((128,128))
    # save as thumb_photo
    f = StringIO.StringIO()
    image.save(f, "JPEG")
    
    self.save_thumb_photo_file(basename(self.full_photo.path), f.getvalue())
  
  def resize(self):
    max_width = self.ad.category.images_max_width
    max_height = self.ad.category.images_max_height
    image = Image.open(self.full_photo.path)
    if image.mode != "RGB":
      image = image.convert('RGB')
    
    height, width = image.size
    if height > max_height or width > max_width:
      image.thumbnail( (max_width, max_height), Image.ANTIALIAS )
      image.save(self.full_photo.path)
    

class FieldValue(models.Model):
  field = models.ForeignKey(Field)
  ad = models.ForeignKey(Ad)
  value = models.TextField()

  def __unicode__(self):
    return self.value
  
class Pricing(models.Model):
  length = models.IntegerField()
  price = models.DecimalField(max_digits=9,decimal_places=2)

  def __unicode__(self):
    return u'$' + unicode(self.price) + u' for ' + str(self.length) + u' days'
  
  class Meta:
    ordering = ['price']
    verbose_name_plural = u'prices'
  
class PricingOptions(models.Model):
  FEATURED_LISTING = 1
  PRICING_OPTIONS = (
    (FEATURED_LISTING, u'Featured Listing'),
  )
  name = models.IntegerField(choices=PRICING_OPTIONS)
  price = models.DecimalField(max_digits=9,decimal_places=2)
  
  def __unicode__(self):
    pricing = {}
    pricing.update(self.PRICING_OPTIONS)
    return pricing[int(self.name)]

  class Meta:
    ordering = ['price']
    verbose_name_plural = u'options'

class ZipCode(models.Model):
  zipcode = models.IntegerField(primary_key=True)
  latitude = models.FloatField()
  longitude = models.FloatField()
  city = models.CharField(max_length=30)
  state = models.CharField(max_length=2)

#CREATE   FUNCTION  `GetNearbyZipCodes`(  
#    zipbase  varchar (6),  
#    range  numeric (15)  
#) RETURNS VARCHAR(5000) DETERMINISTIC
#BEGIN
#DECLARE  lat1  decimal (5,2);  
#DECLARE  long1  decimal (5,2);  
#DECLARE  rangeFactor  decimal (7,6);
#DECLARE  A VARCHAR(5000);  
#SET  rangeFactor = 0.014457;  
#SELECT  latitude,longitude  into  lat1,long1  FROM  adposting_zipcode  WHERE  zipcode = zipbase;  
#SELECT  GROUP_CONCAT(B.zipcode SEPARATOR ',') INTO A  
#FROM  adposting_zipcode  AS  B   
#WHERE
# B.latitude  BETWEEN  lat1-(range*rangeFactor)  AND  lat1+(range*rangeFactor)  
#  AND  B.longitude  BETWEEN  long1-(range*rangeFactor)  AND  long1+(range*rangeFactor)  
#  AND  GetDistance(lat1,long1,B.latitude,B.longitude)  <= range;  
#RETURN A;
#END $$  

  def getNearbyZipCodes(self, radius):
    radius = float(radius)
    rangeFactor = 0.014457
    # bounding box
    objs = ZipCode.objects.filter(latitude__gte=self.latitude-(radius*rangeFactor), latitude__lte=self.latitude+(radius*rangeFactor), longitude__gte=self.longitude-(radius*rangeFactor),longitude__lte=self.longitude+(radius*rangeFactor))
    # if there are any results left, use GetDistance stored function to finish
    if objs.count() > 0:
      objs = objs.extra(where=['GetDistance(%s,%s,latitude,longitude) <= %s'], params=[self.latitude, self.longitude, radius])
    
    return objs

  def __unicode__(self):
    return u'Zip: ' + unicode(self.zipcode) + u', City: ' + self.city + u', State: ' + self.state
  
class SiteSetting(models.Model):
  site = models.ForeignKey(Site)
  name = models.CharField(max_length=100)
  description = models.CharField(max_length=200)
  value = models.CharField(max_length=200)
  
  def __unicode__(self):
    return self.description

from paypal.standard.ipn.models import PayPalIPN

class Payment(models.Model):
  ad = models.ForeignKey(Ad)
  paypal = models.ForeignKey(PayPalIPN, unique=True, null=True)
  pricing = models.ForeignKey(Pricing)
  options = models.ManyToManyField(PricingOptions)
  
  @property
  def paid(self):
    if self.paypal:
      return self.paypal.payment_status == 'Completed'
    else:
      return False
    
  @property
  def amount(self):
    if self.paypal:
      return self.paypal.mc_gross
    else:
      return 0
  
  @property
  def paid_on(self):
    if self.paypal:
      return self.paypal.payment_date
    else:
      return None

from django.contrib.localflavor.us.models import USStateField, PhoneNumberField
class UserProfile(models.Model):
  user = models.ForeignKey(User, unique=True)
  receives_new_posting_notices = models.BooleanField()
  receives_newsletter = models.BooleanField()
  address = models.CharField(max_length=100, blank=True)
  city = models.CharField(max_length=100, blank=True)
  state = USStateField(blank=True)
  zipcode = models.CharField(max_length=10, blank=True)
  phone = PhoneNumberField(blank=True, default='')

