# -*- coding: utf-8 -*-

#from urlparse import urlparse
from urllib.parse import urlparse
import re
import scrapy
from hemnet.items import HemnetItem
from scrapy import Selector

from sqlalchemy.orm import sessionmaker

from hemnet.models import HemnetItem as HemnetSQL, db_connect, create_hemnet_table

# BASE_URL = 'http://www.hemnet.se/salda/bostader?location_ids%5B%5D=17920'

BASE_URL = 'http://www.hemnet.se/salda/bostader?'


def start_urls(start, stop):
    return ['{}&page={}'.format(BASE_URL, x) for x in range(start, stop)]


class HemnetSpider(scrapy.Spider):
    name = 'hemnetspider'
    rotate_user_agent = True

    def __init__(self, start=1, stop=10, *args, **kwargs):
        super(HemnetSpider, self).__init__(*args, **kwargs)
        self.start = int(start)
        self.stop = int(stop)
        engine = db_connect()
        create_hemnet_table(engine)
        self.session = sessionmaker(bind=engine)()

    def start_requests(self):
        for url in start_urls(self.start, self.stop):
            yield scrapy.Request(url, self.parse)

    def parse(self, response):
        urls = response.css('#search-results li > div > a::attr("href")')
        for url in urls.extract():
            session = self.session
            q = session.query(HemnetSQL).filter(HemnetSQL.hemnet_id == get_hemnet_id(url))
            if not session.query(q.exists()).scalar():
                yield scrapy.Request(url, self.parse_detail_page)
            # for att bara kora en i listan
            #break

    def parse_detail_page(self, response):
        item = HemnetItem()
        #Gammalt - ändrat alla med broker-info
        #broker = response.css('.broker-info > p')[0]  # type: Selector
        broker = response.css('.broker-card__info > p')[0]  # type: Selector

        property_attributes = get_property_attributes(response)

        item['url'] = response.url

        slug = urlparse(response.url).path.split('/')[-1]

        item['hemnet_id'] = get_hemnet_id(response.url)

        item['type'] = slug.split('-')[0]

        raw_rooms = property_attributes.get(u'Antal rum', '').replace(u' rum', u'').replace(u',', u'.')

        #flyttar ut ur try tillfälligt
        # item['rooms'] = float(raw_rooms)
        # print(item['rooms'])

        try:
            item['rooms'] = float(raw_rooms)
            print(item['rooms'])
        except ValueError:
            pass

        try:
            fee = int(property_attributes.get(u'Avgift/månad', '').replace(u' kr/m\xe5n', '').replace(u'\xa0', u''))
        except ValueError:
            fee = None
        item['monthly_fee'] = fee

        try:
            item['square_meters'] = float(property_attributes.get(u'Boarea', '').split(' ')[0].replace(',', '.'))
        except ValueError:
            pass
        try:
            cost = int(property_attributes.get(u'Avgift/månad', '').replace(u' kr/m\xe5n', '').replace(u'\xa0', u''))
        except ValueError:
            cost = None

        item['cost_per_year'] = cost
        item['year'] = property_attributes.get(u'Byggår', '')  # can be '2008-2009'

        item['broker_name'] = broker.css('strong::text').extract_first()
        item['broker_phone'] = strip_phone(broker.css('.phone-number::attr("href")').extract_first())

        try:
            email = broker.xpath("a[contains(@href, 'mailto:')]/@href").extract_first().replace(u'mailto:', u'')
            item['broker_email'] = email
        except AttributeError:
            pass

        # Working? Not that interesterd in attributes anyway
        broker_firm=[]
        try:
            broker_firm = response.css('.broker-card__info > p')[1]  # type: Selector
            item['broker_firm'] = broker_firm.css('strong::text').extract_first()
        except IndexError:
            pass


        try:
            firm_phone = broker_firm.xpath("a[contains(@href, 'tel:')]/@href").extract_first()
            item['broker_firm_phone'] = firm_phone.replace(u'tel:', u'')
        except AttributeError:
            pass

        #Gammalt -
        #raw_price = response.css('.sold-property-price > span::text').extract_first()
        raw_price = response.css('.sold-property__price > span::text').extract()[1]

        item['price'] = price_to_int(raw_price)

        get_selling_statistics(response, item)

        detail = response.css('.sold-property__metadata')[0]
        #item['sold_date'] = detail.css('.sold-property__metadata > time::attr("datetime")').extract_first()
        # item['address'] = detail.css('h1::text').extract_first()

        #Nytt
        item['sold_date'] = response.css('.sold-property__metadata > time::attr("datetime")').extract_first()

        #Testar med data från kartan:
        map_string = response.css('.property-map').extract()
        #print(str(map_string))


        item['address'] = map_to_output(str(map_string),"address")

        #item['geographic_area'] = detail.css('.area::text').extract_first().strip().lstrip(u',').strip().rstrip(u',')

        #testar ett alternatvi:
        res_raw = response.css('.sold-property__metadata').getall()
        print(str(res_raw))
        res_raw = res_raw[0].split()

        i=0
        #Geographical area string
        res_string = ""
        flag = False
        while i < len(res_raw):
            if(res_raw[i] == "-"):
                if flag == True:
                    break
                flag = True
            if flag == True and res_raw[i] != "-":
                res_string += res_raw[i] + " "

                print("Hej "+ res_raw[i] + str(i) + " " + res_string)
            i+=1

        item['geographic_area'] = res_string

        coordinates = map_to_output(str(map_string),"coordinates")
        item['x_coordinate'] = float(coordinates[0])
        item['y_coordinate'] = float(coordinates[1])

        yield item


def get_hemnet_id(url):
    slug = urlparse(url).path.split('/')[-1]
    return int(slug.split('-')[-1])


def get_selling_statistics(response, item):

    #Gammalt response.css('.sold-property__price-stats > dd ::text').getall()
    #for li in response.css('ul.selling-statistics > li'):

    #print(response.css('.sold-property__price-stats > ::text').getall())
    res_raw = response.css('.sold-property__price-stats > ::text').getall()

    #Remove blank elements
    res = [s for s in res_raw if len(s.rstrip())>0]
    print(str(res))


    #Lös så att den skippar om den inte hittar värden på dessa
    try:
        i=0
        while i < len(res):
            if res[i] == u'Begärt pris':
                string = re.sub("[^0-9]", "", res[i+1])
                item['asked_price'] = int(string)
            if res[i] == u'Prisutveckling':

                #Måste här hantera att det kan vara negativa priser.
                if "-" in res[i+1]:
                    string2 = "-"+re.search('\(\-(.*?)%', res[i + 1]).group(1)
                    substring1 = re.search('\-(.*?)kr', res[i + 1]).group(1)
                    string1 = "-"+re.sub("[^0-9]", "", substring1)
                else:
                    string2 = re.search('\(\+(.*?)%', res[i + 1]).group(1)
                    substring1 = re.search('\+(.*?)kr', res[i + 1]).group(1)
                    string1 = re.sub("[^0-9]", "", substring1)

                #print("detta rpintas: " + str(string1))
                item['price_trend_flat'] = int(string1)
                item['price_trend_percentage'] = int(string2)
            if res[i] == u'Pris per kvadratmeter':
                string = re.sub("[^0-9]", "", res[i + 1])
                item['price_per_square_meter'] = int(string)
            i+=1
    except IndexError:
        pass

    # #OBS FUNKAR EJ FÖR PRISUTVECKLING - Får lösa på annat sätt.
    # # New solution (not the best but seems to do the work)
    # values = []
    # keys = []
    # for li in response.css('.sold-property__price-stats > dd'):
    #     #key = li.css('::text').extract_first().strip()
    #     value = li.css('::text').extract_first()
    #     values.append(value)
    #
    # for li in response.css('.sold-property__price-stats > dt'):
    #     key = li.css('::text').extract_first().strip()
    #     keys.append(key)
    #
    # test = response.css('.sold-property__price-stats > dd ::text').getall()
    # print("test är: " + str(test))
    #
    #
    #
    # try:
    #     i = 0
    #     while i <= len(values):
    #
    #         if values[i]:
    #             if keys[i] == U'Begärt pris':
    #                 item['asked_price'] = price_to_int(values[i])
    #             if keys[i] == u'Prisutveckling':
    #                 item['price_trend_flat'], item['price_trend_percentage'] = price_trend(values[i])
    #             if keys[i] == u'Pris per kvadratmeter':
    #                 item['price_per_square_meter'] = int(values[i].replace(u'\xa0', '').split(' ')[0])
    #         i += 1
    # except (IndexError, AttributeError) as e:
    #     pass


def get_property_attributes(response):
    # a = response.css('ul.property-attributes > li::text').extract()
    # x = [x.strip() for x in a]
    # b = response.css('ul.property-attributes > li > strong::text').extract()

    #Nytt:
    a = response.css('.sold-property__attributes > dt::text ').extract()
    x = [x.strip() for x in a]
    b = response.css('.sold-property__attributes > dd::text').extract()

    return dict(zip(x, b))


def price_to_int(price_text):
    return int(price_text.replace(u'\xa0', u'').replace(u' kr', u'').encode())


def strip_phone(phone_text):
    if phone_text:
        return phone_text.replace(u'tel:', u'')
    else:
        return u''


def price_trend(price_text):
    r = '(?P<sign>[+-])(?P<flat>\d*)\([+-]?(?P<percentage>\d*)\%\)$'

    temp = price_text.replace(u'\xa0', '').replace(' ', '').replace('kr', '')

    matches = re.search(r, temp)

    sign = matches.group('sign')
    flat = int('{}{}'.format(sign, matches.group('flat')))
    percentage = int('{}{}'.format(sign, matches.group('percentage')))
    return flat, percentage


#Funktion jag skapat för att hämta data ur map-data
def map_to_output(map_string, outp_type):

    if outp_type == "address":
        result = re.search('address&quot;:&quot;(.*?)&', map_string).group(1)
        return result
    elif outp_type == "coordinates":
        coordinates = re.search('coordinate&quot;:(.*?),&', map_string).group(1)
        result = re.findall("[+-]?\d+\.\d+", coordinates)
        return result