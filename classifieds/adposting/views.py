"""
  $Id$
"""
from django.core.context_processors import csrf
from django.shortcuts import render_to_response, get_object_or_404
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.utils.translation import ugettext as _
from django.utils.datastructures import SortedDict

from django.contrib.auth.decorators import login_required
from django.contrib.auth import REDIRECT_FIELD_NAME

from django.template import Context, loader, RequestContext

from django.core.paginator import Paginator, InvalidPage

import datetime

from django.conf import settings

from models import Ad, Field, Category, FieldValue, AdImage, Pricing, PricingOptions
from adform import AdForm

from django import forms

from django.forms.models import inlineformset_factory

from search import *

ADS_PER_PAGE = getattr(settings, 'ADS_PER_PAGE', 5)

from PIL import Image
import string

def clean_adimageformset(self):
    max_size = self.instance.category.images_max_size
    for form in self.forms:
      try:
        if not hasattr(form.cleaned_data['full_photo'], 'file'):
          continue
      except:
        continue

      if form.cleaned_data['full_photo'].size > max_size:
        raise forms.ValidationError(_('Maximum image size is ' + str(max_size/1024) + ' KB'))
      
      im = Image.open(form.cleaned_data['full_photo'].file)
      if self.instance.category.images_allowed_formats.filter(format=im.format).count() == 0:
        raise forms.ValidationError(_('Your image must be in one of the following formats: ') + string.join(self.instance.category.images_allowed_formats.values_list('format', flat=True), ','))
    

def context_sortable(request, ads, perpage=ADS_PER_PAGE):
  order = '-'
  sort = 'expires_on'
  page = 1
  
  if request.GET.has_key('perpage') and request.GET['perpage'] != '':
    perpage = int(request.GET['perpage'])
  
  if request.GET.has_key('order') and request.GET['order'] != '':
    if request.GET['order'] == 'desc':
      order = '-'
    elif request.GET['order'] == 'asc':
      order = ''
      
  if request.GET.has_key('page'):
    page = int(request.GET['page'])
      
  if request.GET.has_key('sort') and request.GET['sort'] != '':
    sort = request.GET['sort']

  if sort in ['created_on', 'expires_on', 'category', 'title']:
    ads_sorted = ads.extra(select={'featured': """SELECT 1
FROM `payment_payment_options`
LEFT JOIN `payment_payment` ON `payment_payment_options`.`payment_id` = `payment_payment`.`id`
LEFT JOIN `adposting_pricing` ON `adposting_pricing`.`id` = `payment_payment`.`pricing_id`
LEFT JOIN `adposting_pricingoptions` ON `payment_payment_options`.`pricingoptions_id` = `adposting_pricingoptions`.`id`
WHERE `adposting_pricingoptions`.`name` = %s
AND `payment_payment`.`ad_id` = `adposting_ad`.`id`
AND `payment_payment`.`paid` =1
AND `payment_payment`.`paid_on` < NOW()
AND DATE_ADD( `payment_payment`.`paid_on` , INTERVAL `adposting_pricing`.`length`
DAY ) > NOW()"""}, select_params=[PricingOptions.FEATURED_LISTING]).extra(order_by=['-featured', order + sort])
  else:
    # sometimes I surprise myself
    ads_sorted = ads.extra(select=SortedDict( [('fvorder', 'select value from adposting_fieldvalue LEFT JOIN adposting_field on adposting_fieldvalue.field_id = adposting_field.id where adposting_field.name = %s and adposting_fieldvalue.ad_id = adposting_ad.id'), ('featured', """SELECT 1
FROM `payment_payment_options`
LEFT JOIN `payment_payment` ON `payment_payment_options`.`payment_id` = `payment_payment`.`id`
LEFT JOIN `adposting_pricing` ON `adposting_pricing`.`id` = `payment_payment`.`pricing_id`
LEFT JOIN `adposting_pricingoptions` ON `payment_payment_options`.`pricingoptions_id` = `adposting_pricingoptions`.`id`
WHERE `adposting_pricingoptions`.`name` = %s
AND `payment_payment`.`ad_id` = `adposting_ad`.`id`
AND `payment_payment`.`paid` =1
AND `payment_payment`.`paid_on` < NOW()
AND DATE_ADD( `payment_payment`.`paid_on` , INTERVAL `adposting_pricing`.`length`
DAY ) > NOW()""")] ), select_params=[sort, PricingOptions.FEATURED_LISTING]).extra(order_by = ['-featured', order + 'fvorder'])
  
  pager = Paginator(ads_sorted, perpage)
  
  try:
    page = pager.page(page)
  except InvalidPage:
    page = {'object_list': False}

  can_sortby_list = []
  sortby_list = ['created_on']
  for category in Category.objects.filter(ad__in=ads.values('pk').query).distinct():
    can_sortby_list += category.sortby_fields.split(',')

  for category in Category.objects.filter(ad__in=ads.values('pk').query).distinct():
    for fieldname, in category.field_set.values_list('name'):
      if fieldname not in sortby_list and fieldname in can_sortby_list:
        sortby_list.append(fieldname)

  for fieldname, in Field.objects.filter(category=None).values_list('name'):
    if fieldname not in sortby_list and fieldname in can_sortby_list:
      sortby_list.append(fieldname)
  
  return {'page': page, 'sortfields': sortby_list, 'no_results': False, 'perpage': perpage}

def index(request):
  if request.user.is_authenticated() and request.user.is_active:
    return HttpResponseRedirect(reverse('adposting.views.create'))
  else:
    return render_to_response('adposting/index.html', {'prices': Pricing.objects.all()}, context_instance=RequestContext(request))    

@login_required
def mine(request):
  ads = Ad.objects.filter(user=request.user, active=True)
  context = context_sortable(request, ads)
  context['sortfields'] = ['id', 'category', 'created_on']
  return render_to_response('adposting/manage.html', context, context_instance=RequestContext(request))

@login_required
def delete(request, adId):
  # find the ad, if available
  ad = get_object_or_404(Ad, pk=adId, active=True)
  
  # make sure that only the owner of the ad can delete it
  if request.user != ad.user:
    return HttpResponseRedirect('%s?%s=%s' % (settings.LOGIN_URL, REDIRECT_FIELD_NAME, urlquote(request.get_full_path())))
  
  ad.delete()
  
  # create status message
  request.user.message_set.create(message='Ad deleted.')
  
  # send the user back to their ad list
  return HttpResponseRedirect(reverse('adposting.views.mine'))

@login_required
def edit(request, adId):
  # find the ad, if available
  ad = get_object_or_404(Ad, pk=adId, active=True)
  
  # make sure that only the owner of the ad can edit it
  if request.user != ad.user:
    return HttpResponseRedirect('%s?%s=%s' % (settings.LOGIN_URL, REDIRECT_FIELD_NAME, urlquote(request.get_full_path())))

  image_count = ad.category.images_max_count
  ImageUploadFormSet = inlineformset_factory(Ad, AdImage, extra=image_count, max_num=image_count, fields=('full_photo',))
  # enforce max width & height on images
  ImageUploadFormSet.clean = clean_adimageformset
  
  if request.method == 'POST':
    imagesformset = ImageUploadFormSet(request.POST, request.FILES, instance=ad)
    form = AdForm(ad, request.POST)
    if form.is_valid() and imagesformset.is_valid():
      form.save()
      imagesformset.save()
      for image in ad.adimage_set.all():
        image.resize()
        image.generate_thumbnail()
      return HttpResponseRedirect(reverse('adposting.views.mine'))
  else:
    imagesformset = ImageUploadFormSet(request.POST, request.FILES, instance=ad)
    form = AdForm(ad)
  
  return render_to_response('adposting/category/' + ad.category.template_prefix + '/edit.html', {'form': form, 'imagesformset': imagesformset, 'ad': ad}, context_instance=RequestContext(request))

def view(request, adId):
  # find the ad, if available
  ad = get_object_or_404(Ad, pk=adId, active=True)
  
  if ad.expires_on < datetime.datetime.now() and ad.user != request.user:
    raise Http404
  
  return render_to_response('adposting/category/' + ad.category.template_prefix + '/view.html', {'ad': ad}, context_instance=RequestContext(request))

@login_required
def view_bought(request, adId):
  request.user.message_set.create(message='Your ad has been successfully posted. Thank You for Your Order!')
  return view(request, adId)

  
@login_required
def create(request):
  # list categories available and send the user to the create_in_category view
  return render_to_response('adposting/category_choice.html', {'categories': Category.objects.all(), 'type': 'create'}, context_instance=RequestContext(request))

@login_required
def create_in_category(request, categoryId):
  # validate categoryId
  category = get_object_or_404(Category, pk=categoryId)
  ad = Ad.objects.create(category=category, user=request.user, expires_on=datetime.datetime.now(), active=False)
  ad.save()
  return create_edit(request, ad.pk)

@login_required
def create_edit(request, adId):
  ad = get_object_or_404(Ad, pk=adId, active=False, user=request.user)
  
  image_count = ad.category.images_max_count
  ImageUploadFormSet = inlineformset_factory(Ad, AdImage, extra=image_count, max_num=image_count, fields=('full_photo',))
  # enforce max width & height on images
  ImageUploadFormSet.clean = clean_adimageformset
  
  if request.method == 'POST':
    imagesformset = ImageUploadFormSet(request.POST, request.FILES, instance=ad)
    form = AdForm(ad, request.POST)
    #raise str(str(form.errors))
    if form.is_valid():# and imagesformset.is_valid():
      ad = form.save()
      if imagesformset.is_valid():
        imagesformset.save()
        for image in ad.adimage_set.all():
          image.resize()
          image.generate_thumbnail()
        
        return HttpResponseRedirect(reverse('adposting.views.create_preview', args=[ad.pk]))
  else:
    imagesformset = ImageUploadFormSet(instance=ad)
    form = AdForm(ad)
  
  return render_to_response('adposting/category/' + ad.category.template_prefix + '/edit.html', {'form': form, 'imagesformset': imagesformset, 'ad': ad, 'create': True}, context_instance=RequestContext(request))
  

@login_required
def create_preview(request, adId):
  ad = get_object_or_404(Ad, pk=adId, active=False, user=request.user)
  
  return render_to_response('adposting/category/' + ad.category.template_prefix + '/preview.html', {'ad': ad, 'create': True}, context_instance=RequestContext(request))

def search(request):
  # list categories available and send the user to the search_in_category view
  return render_to_response('adposting/category_choice.html', {'categories': Category.objects.all(), 'type': 'search'}, context_instance=RequestContext(request))

def search_in_category(request, categoryId):
  try:
    del request.session['search']
  except KeyError:
    pass
  
  return search_results(request, categoryId)

def prepare_sforms(fields, fields_left, post=None):
  sforms = []
  select_fields = {}
  for field in fields:
    if field.field_type == Field.SELECT_FIELD:  # is select field
      # add select field
      options = field.options.split(',')
      choices = zip(options, options)
      choices.insert(0, ('', 'Any',))
      form_field = forms.ChoiceField(label=field.label, required=False, help_text=field.help_text + u'\nHold ctrl or command on Mac for multiple selections.', choices=choices, widget=forms.SelectMultiple)
      # remove this field from fields_list
      fields_left.remove( field.name )
      select_fields[field.name] = form_field
      
  sforms.append(SelectForm.create(select_fields, post))
  
  for sf in searchForms:
    f = sf.create(fields, fields_left, post)
    if f != None:
      sforms.append(f)
  
  return sforms

def search_results(request, categoryId):
  cat = get_object_or_404(Category, pk=categoryId)
  fields = list(cat.field_set.all())
  fields += list(Field.objects.filter(category=None))
  fieldsLeft = [field.name for field in fields]
  
  if request.method == "POST" or request.session.has_key('search'):
    ads = cat.ad_set.filter(active=True,expires_on__gt=datetime.datetime.now())
    # A request dictionary with keys defined for all
    # fields in the category.
    post = {}
    if request.session.has_key('search'):
      post.update(request.session['search'])
    else:
      post.update(request.POST)
    
    sforms = prepare_sforms(fields, fieldsLeft, post)

    isValid = True
    #validErrors = {}
    for f in sforms:
      #TODO: this assumes the form is not required (it's a search form after all)
      if not f.is_valid() and not f.is_empty():
        isValid = False
        #validErrors.update(f.errors)

    if isValid:
      if request.method == 'POST':
        request.session['search'] = {}
        request.session['search'].update(request.POST)
        return HttpResponseRedirect(reverse('adposting.views.search_results', args=[categoryId]))
      
      for f in sforms:
        ads = f.filter(ads)
    
      if ads.count() == 0:
        return render_to_response('adposting/list.html', {'no_results':True, 'category':cat}, context_instance=RequestContext(request))
      else:
        context = context_sortable(request, ads)
        context['category'] = cat
        return render_to_response('adposting/list.html', context, context_instance=RequestContext(request))
  else:
    sforms = prepare_sforms(fields, fieldsLeft)
    
  return render_to_response('adposting/search.html', {'forms':sforms, 'category':cat}, context_instance=RequestContext(request))
  
from forms import CheckoutForm, SubscribeForm
from paypal.standard.forms import PayPalPaymentsForm

def checkout(request, adId):
  ad = get_object_or_404(Ad, pk=adId)
  if request.method == 'POST':
    form = CheckoutForm(request.POST)
    if form.is_valid():
      total = 0
      pricing = Pricing.objects.get(pk=form.cleaned_data["pricing"])
      total += pricing.price
      pricing_options = []
      for pk in form.cleaned_data["pricing_options"]:
        option = PricingOptions.objects.get(pk=pk)
        pricing_options.append(option)
        total += option.price
      
      # create Payment object
      payment = Payment.objects.create(ad=ad, pricing=pricing)
      for option in pricing_options:
        payment.options.add(option)
      
      payment.save()
      
      # send email when done
      # 1. render context to email template
      email_template = loader.get_template('adposting/email/posting.txt')
      context = Context({'ad': ad})
      email_contents = email_template.render(context)
      # 2. send email
      send_mail(_('Your ad will be posted shortly.'), email_contents, settings.FROM_EMAIL, [ad.user.email], fail_silently=False)
      
      item_name = _('Your ad on ') + Site.objects.get_current().name 
      paypal_values = {'amount': total, 'item_name': item_name, 'item_number': payment.pk, 'quantity': 1}
      if settings.DEBUG:
        paypal_form = PayPalPaymentsForm(initial=paypal_values).sandbox()
      else:
        paypal_form = PayPalPaymentsForm(initial=paypal_values).rander()

      return render_to_response('adposting/paypal.html', {'form': paypal_form}, context_instance=RequestContext(request))
  else:
    form = CheckoutForm()
  
  return render_to_response('adposting/checkout.html', {'ad': ad, 'form': form}, context_instance=RequestContext(request))
  
def pricing(request):
  return render_to_response('adposting/pricing.js', {'prices': Pricing.objects.all(), 'options': PricingOptions.objects.all()}, context_instance=RequestContext(request))

def notify_complete(request):
  return render_to_response('adposting/notify_complete.html', {}, context_instance=RequestContext(request))

def notify(request):
  if request.method == 'POST': #form was submitted
    form = SubscribeForm(request.POST)
    if form.is_valid():
      # create user profile
      user = User.objects.create_user(form.cleaned_data["email_address"], form.cleaned_data["email_address"])
      user.first_name = form.cleaned_data["first_name"]
      user.last_name = form.cleaned_data["last_name"]
      user.is_active = False
      user.save()
      profile = UserProfile.objects.create(user=user, receives_new_posting_notices=True, receives_newsletter=True)
      profile.save()
      
      return HttpResponseRedirect(reverse(notify_complete))
  else:
    form = SubscribeForm()

  return render_to_response('adposting/notify.html', {'form': form}, context_instance=RequestContext(request))

