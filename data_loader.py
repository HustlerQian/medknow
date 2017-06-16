#!/usr/bin/python !/usr/bin/env python
# -*- coding: utf-8 -*


# Functions to extract knowledge from medical text. Everything related to 
# reading, parsing and extraction needed for the knowledge base. Also,
# some wrappers for SemRep, MetaMap and Reverb.

import json
import os
import py2neo
import csv
import subprocess
import urllib2
import requests
import unicodecsv as csv2
import pandas as pd
from nltk.tokenize import sent_tokenize
from config import settings
from utilities import time_log





def mmap_extract(text):
    """
    Function-wrapper for metamap binary. Extracts concepts
    found in text.

    !!!! REMEMBER TO START THE METAMAP TAGGER AND
        WordSense DISAMBIGUATION SERVER !!!!
    
    Input:
        - text: str,
        a piece of text or sentence
    Output:
        - concepts: list,
        list of metamap concepts extracted
    """

    # Tokenize into sentences
    sents = sent_tokenize(text)
    mm = MetaMap.get_instance(settings['load']['path']['metamap'])
    concepts, errors = mm.extract_concepts(sents, range(len(sents)), 
                                         word_sense_disambiguation=True)
    if errors:
        time_log('Errors with extracting concepts!')
        time_log(errors)
    return concepts


def runProcess(exe, working_dir):    
    """
    Function that opens a command line and runs a command.
    Captures the output and returns.
    Input:
        - exe: str,
        string of the command to be run. ! REMEMBER TO ESCAPE CHARS!
        - working_dir: str,
        directory where the cmd should be executed
    Output:
        - lines: list,
        list of strings generated from the command
    """

    p = subprocess.Popen(exe, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=working_dir, shell=True)
    lines = p.stdout.readlines()
    return lines


def stopw_removal(inp, stop):
    """
    Stopwords removal in line of text.
    Input:
        - inp: str,
        string of the text input
        - stop: list,
        list of stop-words to be removed 
    """

    # Final string to be returned
    final = ''
    for w in inp.lower().split():
        if w not in stop:
            final += w + ' '
    # Remove last whitespace that was added ' '
    final = final[:-1]
    return final


def reverb_wrapper(text, stop=None):
    """
    Function-wrapper for ReVerb binary. Extracts relations
    found in text.
    Input:
        - text: str,
        a piece of text or sentence
        - stop: list,
        list of stopwords to remove from the relations
    Output:
        - total: list,
        list of lists. Each inner list contains one relation in the form
        [subject, predicate, object]
    """
    total = []
    for sent in sent_tokenize(text):
        cmd = 'echo "' + sent + '"' "| ./reverb -q | tr '\t' '\n' | cat -n"
        reverb_dir = settings['load']['path']['reverb']
        result = runProcess(cmd, reverb_dir)
        # Extract relations from reverb output
        result = result[-3:]
        result = [row.split('\t')[1].strip('\n') for row in result]
        # Remove common stopwords from relations
        if stop:
            result = [stopw_removal(res, stop) for res in result]
        total.append(result)
    # Remove empty relations
    total = [t for t in total if t]
    return total




def cui_to_uri(api_key, cui):
    """
    Function to map from cui to uri if possible. Uses biontology portal
    Input:
        - api_key: str,
        api usage key change it in setting.yaml
        - cui: str,
        cui of the entity we wish to map the uri
    Output:
        - the uri found in string format or None
    """

    REST_URL = "http://data.bioontology.org"
    annotations = get_json_with_api(api_key, REST_URL + "/search?include_properties=true&q=" + urllib2.quote(cui))
    try:
        return annotations['collection'][0]['@id']
    except Exception, e:
        time_log(Exception)
        time_log(e)
        return None

def get_json_with_api(api_key, url):
    """
    Helper funtion to retrieve a json from a url through urlib2
    Input:
        - api_key: str,
        api usage key change it in setting.yaml
        - url: str,
        url to curl
    Output:
        - json-style dictionary with the curl results 
    """

    opener = urllib2.build_opener()
    opener.addheaders = [('Authorization', 'apikey token=' + api_key)]
    return json.loads(opener.open(url).read())


def threshold_concepts(concepts, hard_num=3, score=None):
    """
    Thresholding concepts from metamap to keep only the most probable ones.
    Currently supporting thresholding on the first-N (hard_num) or based on
    the concept score.
    Input:
        - concepts: list,
        list of Metamap Class concepts
        - hard_num: int,
        the first-N concepts to keep, if this thresholidng is selected
        - score: float,
        lowest accepted concept score, if this thresholidng is selected 
    """

    if hard_num:
        if hard_num >= len(concepts):
            return concepts
        elif hard_num < len(concepts):
            return concepts[:hard_num]
    elif score:
            return [c for c in concepts if c.score > score]
    else:
        return concepts
        



def get_name_concept(concept):
    """
    Get name from the metamap concept. Tries different variations and
    returns the name found.
    Input:
        - concept: Metamap class concept, as generated from mmap_extract
        for example
    Output:
        - name: str,
        the name found for this concept
    """

    name = ''
    if hasattr(concept, 'preferred_name'):
        name = concept.preferred_name
    elif hasattr(concept, 'long_form') and hasattr(concept, 'short_form'):
        name = concept.long_form + '|' + concept.short_form
    elif hasattr(concept, 'long_form'):
        name = concept.long_form
    elif hasattr(concept, 'short_form'):
        name =  concept.short_form
    else:
        name = 'NO NAME IN CONCEPT'
    return name



def metamap_ents(x):
    """
    Function to get entities in usable form.
    Exctracts metamap concepts first, thresholds them and
    tries to extract names and uris for the concepts to be
    more usable.
    Input:
        - x: str,
        sentence to extract entities
    Output:
        - ents: list,
        list of entities found. Each entity is a dictionary with
        fields id (no. found in sentence), name if retrieved, cui if 
        available and uri if found
    """

    # API KEY to biontology mapping from cui to uri
    API_KEY = settings['apis']['biont']
    concepts = mmap_extract(x)
    concepts = threshold_concepts(concepts)
    ents = []
    for i, concept in enumerate(concepts):
        ent = {}
        ent['ent_id'] = i
        ent['name'] = get_name_concept(concept)
        if hasattr(concept, 'cui'):
            ent['cui'] = concept.cui
            ent['uri'] = cui_to_uri(API_KEY, ent['cui']) 
        else:
            ent['cui'] = None
            ent['uri'] = None
        ents.append(ent)
    return ents


def extract_entities(text, json_={}):
    """
    Extract entities from a given text using metamap and
    generate a json, preserving infro regarding the sentence
    of each entity that was found. For the time being, we preserve
    both concepts and the entities related to them
    Input:
         - text: str,
        a piece of text or sentence
        - json_: dic,
        sometimes the json to be returned is given to us to be enriched
        Defaults to an empty json_
    Output:
        - json_: dic,
        json with fields text, sents, concepts and entities
        containg the final results
    """
    json_['text'] = text
    # Tokenize the text
    sents = sent_tokenize(text)
    json_['sents'] = [{'sent_id': i, 'sent_text': sent} for i, sent in enumerate(sents)]
    json_['concepts'], _ = mmap_extract(text)
    json_['entities'] = {}
    for i, sent in enumerate(json_['sents']):
        ents = metamap_ents(sent)
        json_['entities'][sent['sent_id']] = ents
    return json_


def enrich_with_triples(results, subject, pred='MENTIONED_IN'):
    """
    Enrich with rdf triples a json dictionary in the form of:
    entity-URI -- MENTIONED_IN -- 'Text 'Title'. Only entities with
    uri's are considered.
    Input:
        - results: dic,
        json-style dictionary genereated from the extract_entities function
        - subject: str,
        the name of the text document in which the entities are mentioned
        - pred: str,
        the predicate to be used as a link between the uri and the title
    Output:
        - results: dic,
        the same dictionary with one more 
    """
    triples = []
    for sent_key, ents in results['entities'].iteritems():
        for ent in ents:
            if ent['uri']:
               triples.append({'subj': ent['uri'], 'pred': pred, 'obj': subject})
    results['triples'] = triples
    return results
        


def semrep_wrapper(text):
    """
    Function wrapper for SemRep binary. It is called with flags
    -F only and changing this will cause this parsing to fail, cause
    the resulting lines won't have the same structure.
    Input:
        - text: str,
        a piece of text or sentence
    Output:
        - results: dic,
        jston-style dictionary with fields text and sents. Each
        sentence has entities and relations found in it. Each entity and
        each relation has attributes denoted in the corresponding
        mappings dictionary. 
    """
    # Exec the binary
    cmd = "echo " + text + " | ./semrep.v1.7 -L 2015 -Z 2015AA -F"
    semrep_dir = settings['load']['path']['semrep']
    lines = runProcess(cmd, semrep_dir)
    # mapping of line elements to fields
    mappings = {
        "text": {
            "sent_id": 4,
            "sent_text": 6
        },
        "entity": {
            'cuid': 6,
            'label': 7,
            'sem_types': 8,
            'score': 15
        },
        "relation": {
            'subject__cui': 8,
            'subject__label': 9,
            'subject__sem_types': 10,
            'subject__sem_type': 11,
            'subject__score': 18,
            'predicate__type': 21,
            'predicate': 22,
            'negation': 23,
            'object__cui': 28,
            'object__label': 29,
            'object__sem_types': 30,
            'object__sem_type': 31,
            'object__score': 38,
        }
    }
    results = {'sents': [], 'text': text}
    for line in lines:
        # If Sentence
        if line.startswith('SE'):
            elements = line.split('|')
            # New sentence that was processed
            if elements[5] == 'text':
                tmp = {"entities": [], "relations": []}
                for key, ind in mappings['text'].iteritems():
                    tmp[key] = elements[ind]
                results['sents'].append(tmp)
            # A line containing entity info
            if elements[5] == 'entity':
                tmp = {}
                for key, ind in mappings['entity'].iteritems():
                    if key == 'sem_types':
                        tmp[key] = elements[ind].split(',')
                    tmp[key] = elements[ind]
                results['sents'][-1]['entities'].append(tmp)
            # A line containing relation info
            if elements[5] == 'relation':
                tmp = {}
                for key, ind in mappings['relation'].iteritems():
                    if 'sem_types' in key:
                        tmp[key] = elements[ind].split(',')
                    else:
                        tmp[key] = elements[ind]
                results['sents'][-1]['relations'].append(tmp)
    return results


def clean_text(text):
    """
    Escape specific characters for command line call of SemRep. This
    could be updated in the future to more sophisticated transformations.
    Input:
        - text: str,
        piece of text to clean
    Output:
        - text: str,
        the same text with cmd escaped parenthesis and removing '
    """

    text = text.replace('(', '\(').replace(')', '\)').replace("'",  ' ')
    return text


def extract_semrep(json_, key):
    """
    Task function to parse and extract concepts from json_ style dic, using
    the SemRep binary.
    Input:
        - json_ : dic,
        json-style dictionary generated from the Parse object related
        to the specific type of input
        - key : str,
        string denoting the type of medical text to read from. Used to
        find the correct paragraph in the settings.yaml file.
    Output:
        - json_ : dic,
        the previous json-style dictionary enriched with medical concepts
    """
    # outerfield for the documents in json
    docfield = settings['out']['json']['json_doc_field']
    # textfield to read text from
    textfield = settings['out']['json']['json_text_field']
    N = len(json_[docfield])
    for i, doc in enumerate(json_[docfield]):
        text = clean_text(doc[textfield])
        results = semrep_wrapper(text)
        json_[docfield][i].update(results)
        proc = int(i/float(N)*100)
        if proc % 10 == 0:
            time_log('We are at %d/%d documents -- %0.2f %%' % (i, N, proc))
    return json_


def parse_medical_rec():
    """
    Parse file containing medical records.
    Output:
        - json_ : dic,
        json-style dictionary with documents containing
        a list of dicts, containing the medical record and the corresponding
        attributes
    """

    # input file path from settings.yaml
    inp_path = settings['load']['med_rec']['inp_path']
    # csv seperator from settings.yaml
    sep = settings['load']['med_rec']['sep']
    # textfield to read text from
    textfield = settings['load']['med_rec']['textfield']
    # idfield where id of document is stored
    idfield = settings['load']['med_rec']['idfield']
    with open(inp_path, 'r') as f:
        diag = pd.DataFrame.from_csv(f, sep='\t')
    # Get texts
    texts = diag[textfield].values
    # outerfield for the documents in json
    docfield = settings['out']['json']['json_doc_field']
    # textfield to read text from
    out_textfield = settings['out']['json']['json_text_field']
    # idfield where id of document is stored
    out_idfield = settings['out']['json']['json_id_field']
    # labelfield where title of the document is stored
    out_labelfield = settings['out']['json']['json_label_field']
    diag[out_labelfield] = ['Medical Record' + str(i) for i in diag.index.values.tolist()]
    diag['journal'] = ['None' for i in diag.index.values.tolist()]
    # Replace textfiled with out_textfield
    diag[out_textfield] = diag[textfield]
    del diag[textfield]
    # Replace id with default out_idfield
    diag[out_idfield] = diag[idfield]
    del diag[idfield]
    json_ = {docfield: diag.to_dict(orient='records')}
    return json_


def parse_json():
    """
    Parse file containing articles.
    Output:
        - json_ : dic,
        json-style dictionary with documents containing
        a list of dicts, with field text, containing the attributes of
        the article
    """

    # input file path from settings.yaml
    inp_path = settings['load']['json']['inp_path']
    with open(inp_path, 'r') as f:
        json_ = json.load(f, encoding='utf-8')

    # docfield containing list of elements containing text
    outfield = settings['load']['json']['docfield']
    # textfield to read text from
    textfield = settings['load']['json']['textfield']
    # idfield where id of document is stored
    idfield = settings['load']['json']['idfield']
    # labelfield where title of the document is stored
    labelfield = settings['load']['json']['labelfield']
    
    ## Values to replace them with ##

    # docfield containing list of elements
    out_outfield = settings['out']['json']['json_doc_field']
    # textfield to read text from
    out_textfield = settings['out']['json']['json_text_field']
    # idfield where id of document is stored
    out_idfield = settings['out']['json']['json_id_field']
    # labelfield where title of the document is stored
    out_labelfield = settings['out']['json']['json_label_field']
    for article in json_[outfield]:
        article[out_textfield] = article.pop(textfield)
        article[out_idfield] = article.pop(idfield)
        article[out_labelfield] = article.pop(labelfield)
    json_[out_outfield] = json_.pop(outfield)
    return json_

def parse_edges():
    """
    Parse file containing edges-relations between nodes.
    Output:
        - json_ : dic,
        json-style dictionary with field medical_records containing
        a list of dicts, with field text, containing the medical record
        json_ = {'medical_records': [{'text':...}, {'text':...}]}
    """

    # input file path from settings.yaml
    inp_path = settings['load']['edges']['inp_path']
    with open(inp_path, 'r') as f:
        json_ = json.load(f, encoding='utf-8')
    

    # docfield containing list of elements
    out_outfield = settings['out']['json']['json_doc_field']
    # textfield to read text from
    out_textfield = settings['out']['json']['json_text_field']
    # idfield where id of document is stored
    out_idfield = settings['out']['json']['json_id_field']
    # labelfield where title of the document is stored
    out_labelfield = settings['out']['json']['json_label_field']


#results = extract_entities(text)
#results = enrich_with_triples(results, subject='Text Title')
