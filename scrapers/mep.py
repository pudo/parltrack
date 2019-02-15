#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#    This file is part of parltrack

#    parltrack is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    parltrack is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with parltrack  If not, see <http://www.gnu.org/licenses/>.

# (C) 2019 by Stefan Marsiske, <parltrack@ctrlc.hu>

import re,sys
from utils.utils import fetch, fetch_raw, unws, jdump
from utils.mappings import buildings, SEIRTNUOC, COMMITTEE_MAP, ORGMAPS, GROUP_MAP, DELEGATIONS
from datetime import datetime
from lxml.html.soupparser import fromstring

CONFIG = {
    'threads': 8,
    'timeout': 60,
    'retries': 5,
    'error_handler': None,
}


def deobfus_mail(txt):
    x = txt.replace('[at]','@').replace('[dot]','.')
    return ''.join(x[len('mailto:'):][::-1])

def parse_addr(root):
    # addresses
    addrs = {}
    for li in root.xpath('//div[@class="ep-a_contacts"]/ul/li'):
        key = unws(''.join(li.xpath('.//h3//text()')))
        addrs[key]={}
        if key in ['Brussels', 'Bruxelles', 'Strasbourg']:
            addrs[key]['phone']=li.xpath('.//li[@class="ep_phone"]/a/@href')[0][4:]
            addrs[key]['fax']=li.xpath('.//li[@class="ep_fax"]/a/@href')[0][4:]
        tmp=[unws(x) for x in li.xpath('.//div[@class="ep_information "]//text()') if len(unws(x))]
        if key=='Strasbourg':
            addrs[key][u'Address']=dict(zip([u'Organization',u'Building', u'Office', u'Street',u'Zip1', u'Zip2'],tmp))
            addrs[key][u'Address']['City']=addrs[key]['Address']['Zip2'].split()[1]
            addrs[key][u'Address']['Zip2']=addrs[key]['Address']['Zip2'].split()[0]
            addrs[key][u'Address']['building_code']=buildings.get(addrs[key]['Address']['Building'])
        elif key==u'Brussels' or key==u'Bruxelles':
            addrs[key][u'Address']=dict(zip([u'Organization',u'Building', u'Office', u'Street',u'Zip'],tmp))
            addrs[key][u'Address']['City']=addrs[key]['Address']['Zip'].split()[1]
            addrs[key][u'Address']['Zip']=addrs[key]['Address']['Zip'].split()[0]
            addrs[key][u'Address']['building_code']=buildings.get(addrs[key]['Address']['Building'])
        elif key=='Luxembourg':
            addrs[key][u'Address']=tmp
        elif key=='Postal address':
            addrs[key]=tmp
    return addrs

def parse_hist_date(txt):
    tmp = txt.split(' / ')
    if len(tmp)==2:
        (start, end) = tmp
    elif len(tmp)==1:
        start = txt.split()[0]
        end = "31-12-9999"
    else:
        raise ValueError
    return datetime.strptime(unws(start), u"%d-%m-%Y"), datetime.strptime(unws(end), u"%d-%m-%Y")

def parse_acts(id, terms):
    activity_types=(('plenary-speeches', 'CRE'),
                    ('reports', "REPORT"),
                    ('reports-shadow', "REPORT-SHADOW"),
                    ('opinions', "COMPARL"),
                    ('opinions-shadow', "COMPARL-SHADOW"),
                    ('motions-instit', "MOTION"),
                    ('oral-questions', "ORAL"),
                    # other activities
                    ('written-explanations', 'WEXP'),
                    ('written-questions', "WQO"),
                    ('motions-indiv', "IMOTION"),
                    ('written-declarations', "WDECL"))
    activities={}
    for type, TYPE in activity_types:
        for term in terms:
            start = 0
            cnt = 100
            url = "http://www.europarl.europa.eu/meps/en/%s/loadmore-activities/%s/%s/?from=%s&count=%s" % (id, type, term, start, cnt)
            root = fetch(url)
            print(url, file=sys.stderr)
            while(len(root.xpath('//article'))>0):
                for node in root.xpath('//article'):
                    if type == 'written-explanations':
                        item = {
                            'title': unws(''.join(node.xpath('.//div[@class="ep-p_text erpl-activity-title"]//text()'))),
                            'date': datetime.strptime(node.xpath('.//time/@datetime')[0], u"%Y-%m-%dT%H:%M:%S"),
                            'date-type': node.xpath('.//time/@itemprop')[0],
                            'text': unws(''.join(node.xpath('.//div[@class="ep-a_text"]//text()')))}
                    elif type == 'written-declarations':
                        item = {
                            'title': unws(''.join(node.xpath('.//div[@class="ep-p_text erpl-activity-title"]//text()'))),
                            'date': datetime.strptime(node.xpath('.//time/@datetime')[0], u"%Y-%m-%dT%H:%M:%S"),
                            'date-type': node.xpath('.//time/@itemprop')[0],
                            'formats': [{'type': unws(fnode.xpath('./text()')[0]),
                                        'url': fnode.xpath('./@href')[0],
                                        'size': unws(fnode.xpath('./span/text()')[0])}
                                        for fnode in node.xpath('.//div[@class="ep-a_links"]//a')],
                            'authors': unws(''.join(node.xpath('.//span[@class="ep_name erpl-biblio-authors"]//text()'))),
                        }
                        for info in node.xpath('.//span[@class="erpl-biblio-addinfo"]'):
                            label, value = info.xpath('.//span[@class="erpl-biblio-addinfo-label"]')
                            label = unws(''.join(label.xpath('.//text()')))[:-2]
                            value = unws(''.join(value.xpath('.//text()')))
                            if 'date' in label.lower():
                                value = datetime.strptime(value, u"%d-%m-%Y")
                            if label == 'Number of signatories':
                                number, date = value.split(' - ')
                                value = int(number)
                                item["No of sigs date"] = datetime.strptime(date, u"%d-%m-%Y")
                            item[label]=value
                    else:
                        # all other activities share the following scraper
                        ref = unws(''.join(node.xpath('.//time/following-sibling::text()')))
                        if ref.startswith('- '):
                            ref = ref[2:]
                        if ref.endswith(' -'):
                            ref = ref[:-2]

                        item = {
                            'url': node.xpath('.//a/@href')[0],
                            'title': unws(''.join(node.xpath('.//a//text()'))),
                            'date': datetime.strptime(node.xpath('.//time/@datetime')[0], u"%Y-%m-%dT%H:%M:%S"),
                            'date-type': node.xpath('.//time/@itemprop')[0],
                            'reference': ref,
                        }

                        abbr = unws(''.join(node.xpath('.//abbr/text()')))
                        if abbr:
                            item['committee']=abbr

                        formats = []
                        for fnode in node.xpath('.//div[@class="ep-a_links"]//a'):
                            elem = {'type': unws(fnode.xpath('./text()')[0]),
                                    'url': fnode.xpath('./@href')[0]}
                            tmp=fnode.xpath('./span/text()')
                            if len(tmp) > 0:
                                elem['size']=unws(tmp[0])
                            formats.append(elem)
                        if formats:
                            item['formats']=formats

                    item['term']=term
                    if TYPE not in activities:
                        activities[TYPE]=[]
                    activities[TYPE].append(item)
                start += cnt
                url = "http://www.europarl.europa.eu/meps/en/%s/loadmore-activities/%s/%s/?from=%s&count=%s" % (id, type, term, start, cnt)
                root = fetch(url)
                print(url, file=sys.stderr)
    return activities

def scrape(id):
    # we ignore the /meps/en/<id>/<name>/home path, since we can get all info also from other pages
    url = "http://www.europarl.europa.eu/meps/en/%s/name/cv" % id
    xml = fetch_raw(url) # we have to patch up the returned html...
    xml = xml.replace("</br>","<br/>") # ...it contains some bad tags..
    root = fromstring(xml) # ...which make the lxml soup parser drop some branches in the DOM

    body = root.xpath('//span[@id="mep-card-content"]/following-sibling::div')[0]
    mep = {
        'MepID'     : id,
        'name'      : unws(' '.join(root.xpath('//*[@id="name-mep"]//text()'))),
        'twitter'   : root.xpath('//div[@class="ep_share"]//a[@title="Twitter"]/@href'),
        'homepage'  : root.xpath('//div[@class="ep_share"]//a[@title="Website"]/@href'),
        'facebook'  : root.xpath('//div[@class="ep_share"]//a[@title="Facebook"]/@href'),
        'email'     : [deobfus_mail(x) for x in root.xpath('//div[@class="ep_share"]//a[@title="E-mail"]/@href')],
        'instagram' : root.xpath('//div[@class="ep_share"]//a[@title="Instagram"]/@href'),
        'Birth'     : {
            'date'  : datetime.strptime(root.xpath('//time[@id="birthDate"]/text()')[0], u"%d-%m-%Y"),
            'place' : root.xpath('//span[@id="birthPlace"]/text()')[0]
        },
        'addresses' : parse_addr(root),
    }
    if not body.xpath('//span[@id="no_cv_available"]'):
        mep['cv']= {'updated': datetime.strptime(root.xpath('//span[starts-with(text(),"Updated: ")]/text()')[0], u"Updated: %d/%m/%Y")}
        mep['cv'].update({unws(''.join(title.xpath(".//text()"))): [unws(''.join(item.xpath(".//text()")))
                                                                    for item in title.xpath("../../../article//li")]
                        for title in body.xpath('.//h3')
                        if not unws(''.join(title.xpath(".//text()"))).startswith("Original version : ")})

    # assistants
    root = fetch("http://www.europarl.europa.eu/meps/en/%s/name/assistants" % id)
    body = root.xpath('//span[@id="mep-card-content"]/following-sibling::div')[0]
    mep['assistants'] = {unws(''.join(title.xpath(".//text()"))): [unws(''.join(item.xpath(".//text()")))
                                                                for item in title.xpath("../../../article//li")]
                      for title in body.xpath('.//h3')}
    # declarations
    root = fetch("http://www.europarl.europa.eu/meps/en/%s/name/declarations" % id)
    body = root.xpath('//span[@id="mep-card-content"]/following-sibling::div')[0]
    for title in body.xpath('.//h3'):
        key = unws(''.join(title.xpath('.//text()')))
        if key == 'Declaration of financial interests':
            key = 'Financial Declarations'
        elif key == 'Declarations of participation by Members in events organised by third parties':
            key = 'Declarations of Participation'
        else:
            print("unknown type of declaration:", key, "http://www.europarl.europa.eu/meps/en/%s/name/declarations" % id)
            key = None
        if key is not None:
            mep[key] = []
            for pdf in title.xpath('../../following-sibling::div//li//a'):
                name = unws(''.join(pdf.xpath('.//text()')))
                url = pdf.xpath('./@href')[0]
                mep[key].append({'title': name, 'url': url})
                if key == 'Financial Declarations':
                    scraper_service.add_job('findecl', payload={'id':id, 'url', url})

    # history
    terms = []
    for term in root.xpath('//nav[@class="ep_tableofcontent-menu table-of-contents-menu"]//span[text()="History of parliamentary service"]/../../..//li//span[@class="ep_name"]//text()'):
        if not term.endswith("parliamentary term"):
            print("history menu item does not end as expected with \"parliamentary term\":", term, "http://www.europarl.europa.eu/meps/en/%s/name/declarations" % id)
            continue
        term = int(term[0])
        terms.append(term)

        root = fetch("http://www.europarl.europa.eu/meps/en/%s/name/history/%s" % (id, term))
        body = root.xpath('//span[@id="mep-card-content"]/following-sibling::div')[0]
        for title in body.xpath('.//div[@class="ep_gridrow ep-o_productlist"]//h3'):
            key = unws(''.join(title.xpath('.//text()')))
            if key is None:
                print("empty history section", "http://www.europarl.europa.eu/meps/en/%s/name/history/%s" % (id,term))
                continue
            #mep[key] = []
            for item in title.xpath('../../following-sibling::article//li'):
                interval = unws(''.join(item.xpath('./strong/text()')))
                post = item.xpath('./strong/following-sibling::text()')[0][3:]
                if key=="National parties":
                    key='Constituencies'
                    # parse date interval
                    try:
                        start, end = parse_hist_date(interval)
                    except:
                        print("illegal date interval:", interval, "http://www.europarl.europa.eu/meps/en/%s/name/history/%s" % (id,term))
                        continue
                    # parse party and country
                    cstart = post.rfind(' (')
                    if post[cstart+2:-1] in SEIRTNUOC:
                        country = post[cstart+2:-1]
                        party = post[:cstart]
                    else:
                        logger.warn('unknown country: %s' % post[cstart+2:-1])
                        country='unknown'
                    if not key in mep: mep[key]=[]
                    mep[key].append({u'party': party, u'country': country, u'start': start, u'end': end, 'term': term})
                elif key in ['Member', 'Substitute', 'Chair', 'Vice-Chair', 'Co-President', 'President', 'Vice-President', 'Observer', 'Quaestor', 'Substitute observer']:
                    # memberships in various committees, delegations and EP mgt
                    try:
                        start, end = parse_hist_date(interval)
                    except:
                        print("illegal date interval:", interval, "http://www.europarl.europa.eu/meps/en/%s/name/history/%s" % (id,term))
                        continue
                    item={u'role': key,
                        u'Organization': post,
                        u'start': start,
                        u'end': end,
                        u'term': term,
                        }
                    for start, field in ORGMAPS:
                        if item['Organization'].startswith(start):
                            if field=='Committees':
                                if item['Organization'] in COMMITTEE_MAP:
                                    item[u'abbr']=COMMITTEE_MAP[item['Organization']]
                                else:
                                    print("no abbr found for committee:", item)
                            if field=='Delegations':
                                if item['Organization'] in DELEGATIONS:
                                    item[u'abbr']=DELEGATIONS[item['Organization']]
                                else:
                                    print("no abbr found for delegation:", item)
                            if not field in mep: mep[field]=[]
                            mep[field].append(item)
                            break
                elif key == u'Political groups':
                    try:
                        start, end = parse_hist_date(interval)
                    except:
                        print("illegal date interval:", interval, "http://www.europarl.europa.eu/meps/en/%s/name/history/%s" % (id,term))
                        continue
                    tmp = post.split(u' - ')
                    if len(tmp)>1:
                        org = ' - '.join(tmp[:-1])
                        role = tmp[-1]
                    elif post.endswith(' -'):
                        org=post[:-2]
                        role=''
                    else:
                        logger.error('[!] political group line %s' % line)
                        continue
                    if not u'Groups' in mep: mep[u'Groups']=[]
                    mep[u'Groups'].append(
                        {u'role':        role,
                        u'Organization': org,
                        # u'country':      country, # this value is missing from the latest EP website
                        u'groupid':      GROUP_MAP[org],
                        u'start':        start,
                        u'end':          end,
                        })
                else:
                    logger.error('[!] unknown field %s' % key)

    # activities
    mep['activities']=parse_acts(id, terms)

    print(jdump(mep))

    # activities
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/main-activities/plenary-speeches
    # or /meps/en/96674/loadmore-activities/plenary-speeches/8/?from=10&count=100
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/main-activities/reports
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/main-activities/reports-shadow
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/main-activities/opinions-shadow
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/main-activities/motions-instit
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/main-activities/oral-questions

    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/other-activities/written-explanations
    # or /meps/en/96674/loadmore-activities/written-explanations/8/?from=10&count=100
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/other-activities/written-questions-other
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/other-activities/motions-indiv
    # /meps/en/96674/ANNA+MARIA_CORAZZA+BILDT/other-activities/written-declarations

if __name__ == '__main__':
    #scrape(28390)
    #scrape(96779)
    scrape(96674)
