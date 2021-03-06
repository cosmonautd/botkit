""" Natural Language Understanding module
"""

import os
import json
import copy
import string
import operator

import mitie
import spacy
import textblob

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

try:
    import botkit.external.python_tf_idf.tfidf as tfidf
    import botkit.util as util
except:
    import external.python_tf_idf.tfidf as tfidf
    import util

spacy_nlp = spacy.load('en')

emoji_patterns = [':)', ':(', ':D', 'D:', ':/', '@_@', 'o_o', '0_0', ':s', ':p', ':b']

class TfIdfIntentProcessor:
    """
    """
    def __init__(self):
        self.table = None
        self.ignore_pos = ['DET']

    def train(self):
        raise NotImplementedError

    def load(self):
        with open('data/training.json') as training_file:
            training = json.load(training_file)
            intents = dict()
            for sample in training['samples']:
                if sample['intent'] not in intents.keys():
                    intents[sample['intent']] = list()
                sample_doc = spacy_nlp(sample['text'])
                tokens = [token.text.lower() for token in sample_doc]
                for entity in sample['entities']:
                    tokens[entity['start']:entity['stop']] = ['#%s#' % (entity['type'])]
                for i, _ in enumerate(tokens):
                    if sample_doc[i].pos_ in self.ignore_pos: del tokens[i]
                intents[sample['intent']] += tokens

            self.table = tfidf.TfIdf()
            for intent in intents.keys():
                tokens = list(set(intents[intent]))
                self.table.add_document(intent, tokens)

    def classify(self, text):
        tokens = [token.text.lower() for token in spacy_nlp(text) if token.pos_ not in self.ignore_pos]
        tokens = util.preserve_entity_annotations(tokens)
        results = self.table.similarities(tokens)
        output = {result[0]: result[1] for result in results}
        return output

class MitIntentProcessor:
    """
    """
    def __init__(self):
        self.categorizer = None
        self.ignore_pos = ['DET']

    def train(self):
        with open('data/training.json') as training_file:
            training = json.load(training_file)
            try: trainer = mitie.text_categorizer_trainer("models/total_word_feature_extractor.dat")
            except: trainer = mitie.text_categorizer_trainer("botkit/models/total_word_feature_extractor.dat")
            for sample in training['samples']:
                sample_doc = spacy_nlp(sample['text'])
                tokens = [token.text.lower() for token in sample_doc]
                for entity in sample['entities']:
                    tokens[entity['start']:entity['stop']] = ['#%s#' % (entity['type'])]
                for i, _ in enumerate(tokens):
                    if sample_doc[i].pos_ in self.ignore_pos: del tokens[i]
                trainer.add_labeled_text(tokens, sample['intent'])
            trainer.num_threads = 2
            self.categorizer = trainer.train()
            if not os.path.exists('models'): os.mkdir('models')
            self.categorizer.save_to_disk("models/categorizer_model.dat")

    def load(self):
        self.categorizer = mitie.text_categorizer("models/categorizer_model.dat")

    def classify(self, text):
        tokens = [token.text.lower() for token in spacy_nlp(text) if token.pos_ not in self.ignore_pos]
        tokens = util.preserve_entity_annotations(tokens)
        result = self.categorizer(tokens)
        output = {result[0]: result[1]}
        return output

class IntentProcessor:
    """
    """

    def __init__(self):
        self.processor = TfIdfIntentProcessor()

    def train(self):
        self.processor.train()

    def load(self):
        self.processor.load()

    def classify(self, text):
        return self.processor.classify(text)

class MitEntityProcessor:
    """
    """
    def __init__(self):
        self.ner = None

    def train(self):
        with open('data/training.json') as training_file:
            training = json.load(training_file)
        examples = list()
        for sample in training['samples']:
            examples.append(mitie.ner_training_instance([token.text for token in spacy_nlp(sample['text'])]))
            for entity in sample['entities']:
                examples[-1].add_entity(range(entity['start'], entity['stop']), entity['type'])
        try: trainer = mitie.ner_trainer("models/total_word_feature_extractor.dat")
        except: trainer = mitie.ner_trainer("botkit/models/total_word_feature_extractor.dat")
        trainer.num_threads = 2
        for example in examples:
            trainer.add(example)
        self.ner = trainer.train()
        if not os.path.exists('models'): os.mkdir('models')
        self.ner.save_to_disk("models/ner_model.dat")

    def load(self):
        self.ner = mitie.named_entity_extractor('models/ner_model.dat')

    def recognize(self, text):
        output = list()
        tokens = [token.text if token.text not in emoji_patterns else None for token in spacy_nlp(text)]
        entities = self.ner.extract_entities(tokens)
        for range_, type_, confidence in entities:
            entity = dict()
            entity['type'] = type_
            entity['name'] = " ".join(tokens[i] for i in range_)
            entity['confidence'] = confidence
            entity['start'] = range_[0]
            entity['stop'] = range_[-1] + 1
            output.append(entity)
        return output

class EntityProcessor:
    """
    """
    def __init__(self):
        self.processor = MitEntityProcessor()

    def train(self):
        self.processor.train()

    def load(self):
        self.processor.load()

    def recognize(self, text):
        return self.processor.recognize(text)

class Context:
    """ Context handler
    """

    def __init__(self):
        """ Context constructor
        """
        self.context_file = 'context.json'
        self.__load__()

    def __load__(self):
        """ Load context from file or create it for the first time
        """
        context = None
        if os.path.exists(self.context_file):
            with open(self.context_file) as context_file:
                context = json.load(context_file)
        else:
            with open(self.context_file, 'w') as context_file:
                context = dict()
                json.dump(context, context_file)
        return context

    def __commit__(self, context):
        """ Commit changes to context file
        """
        if not context is None:
            with open(self.context_file, 'w') as context_file:
                json.dump(context, context_file)

    def read(self, user, key):
        """ Read from context
        """
        context = self.__load__()
        if user in context:
            if key in context[user]:
                return context[user][key]
            else: return None
        else: return None

    def write(self, user, key, value):
        """ Write to context
        """
        if not self.has_user(user):
            self.add_user(user)
        context = self.__load__()
        context[user][key] = value
        self.__commit__(context)

    def has_user(self, user):
        """ Test if there's context for a user
        """
        context = self.__load__()
        return user in context

    def add_user(self, user):
        """ Add a user to context
        """
        context = self.__load__()
        if not user in context:
            context[user] = dict()
            context[user]['main_context'] = str()
            self.__commit__(context)

    def has_key(self, user, key):
        """ Test if given key exists for user
        """
        context = self.__load__()
        if self.has_user(user):
            if key in context[user]:
                return True
        return False

class NLU:
    """ Natural Language Understanding class
    """
    def __init__(self, disable=list()):
        """
        """
        self.disable = disable

        if 'intents' not in disable:
            self.intent_processor = IntentProcessor()
            try: self.intent_processor.load()
            except: self.intent_processor.train()

        if 'entities' not in disable:
            self.entity_processor = EntityProcessor()
            try: self.entity_processor.load()
            except: self.entity_processor.train()

    def pipe(self, f_list, data):
        output = data
        for f in f_list:
            output = f(output)
        return output

    def preprocess(self, data):
        output = data
        return output

    def language(self, data):
        """
        """
        output = data
        blob = textblob.TextBlob(data['text'] + "   ")
        output['language'] = blob.detect_language()
        try: output['text_en'] = str(blob.translate(to='en')).strip()
        except: pass
        return output

    def sentiments(self, data):
        """
        """
        output = data
        if 'text_en' in data:
            scores = SentimentIntensityAnalyzer().polarity_scores(data['text_en'])
        else:
            scores = SentimentIntensityAnalyzer().polarity_scores(data['text'])
        output['sentiments'] = {
            "compound" : scores['compound'],
            "positive" : scores['pos'],
            "negative" : scores['neg'],
            "neutral"  : scores['neu']
        }
        return output

    def entities(self, data):
        output = data
        if 'text_en' in data:
            output['entities'] = self.entity_processor.recognize(data['text_en'])
            output['tokens_tagged'] = [token.text for token in spacy_nlp(data['text_en'])]
        else:
            output['entities'] = self.entity_processor.recognize(data['text'])
            output['tokens_tagged'] = [token.text for token in spacy_nlp(data['text'])]
        for entity in output['entities']:
            output['tokens_tagged'][entity['start']:entity['stop']] = ['#%s#' % entity['type']]
        output['text_tagged'] = util.untokenize(output['tokens_tagged'])
        return output

    def intents(self, data):
        output = data
        if 'text_tagged' in data: output['intents'] = self.intent_processor.classify(data['text_tagged'])
        elif 'text_en' in data: output['intents'] = self.intent_processor.classify(data['text_en'])
        else: output['intents'] = self.intent_processor.classify(data['text'])
        maxintent = max(output['intents'], key=output['intents'].get)
        if output['intents'][maxintent] > 0.1: output['intent'] = maxintent
        else: output['intent'] = 'none'
        return output

    def postprocess(self, data):
        output = data
        try:
            del output['tokens_tagged']
        except:
            pass
        return output

    def compute(self, text):
        """
        """
        data = {'text': text}

        pipeline = list()
        pipeline.append(self.preprocess)
        if 'language' not in self.disable: pipeline.append(self.language)
        if 'sentiments' not in self.disable: pipeline.append(self.sentiments)
        if 'entities' not in self.disable: pipeline.append(self.entities)
        if 'intents'  not in self.disable: pipeline.append(self.intents)
        pipeline.append(self.postprocess)

        return self.pipe(pipeline, data)

if __name__ == '__main__':

    import time

    bot = NLU()

    start = time.time()
    result = bot.compute("Who is David?")
    print("Processing time: %.3fs" % (time.time() - start))
    print(json.dumps(result, indent=4, sort_keys=True, ensure_ascii=False))
