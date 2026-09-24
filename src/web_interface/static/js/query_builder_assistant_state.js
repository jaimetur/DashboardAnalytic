(() => {
  'use strict';

  class QueryParseError extends Error {}

  const tokenize = (sql) => {
    const tokens = [];
    let index = 0;

    while (index < sql.length) {
      const character = sql[index];
      if (/\s/.test(character)) {
        index += 1;
        continue;
      }

      if (character === '"' || character === "'") {
        const delimiter = character;
        const type = delimiter === '"' ? 'identifier' : 'string';
        let value = '';
        index += 1;
        let closed = false;
        while (index < sql.length) {
          if (sql[index] !== delimiter) {
            value += sql[index];
            index += 1;
          } else if (sql[index + 1] === delimiter) {
            value += delimiter;
            index += 2;
          } else {
            index += 1;
            closed = true;
            break;
          }
        }
        if (!closed) throw new QueryParseError('Unterminated quoted token.');
        tokens.push({type, value});
        continue;
      }

      const numberMatch = sql.slice(index).match(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/);
      if (numberMatch) {
        tokens.push({type: 'number', value: numberMatch[0]});
        index += numberMatch[0].length;
        continue;
      }

      const wordMatch = sql.slice(index).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      if (wordMatch) {
        tokens.push({type: 'word', value: wordMatch[0]});
        index += wordMatch[0].length;
        continue;
      }

      if (sql.startsWith('<>', index)) {
        tokens.push({type: 'symbol', value: '<>'});
        index += 2;
        continue;
      }
      if ('(),=><'.includes(character)) {
        tokens.push({type: 'symbol', value: character});
        index += 1;
        continue;
      }
      throw new QueryParseError('Unsupported SQL token.');
    }

    return tokens;
  };

  class GeneratedQueryParser {
    constructor(tokens) {
      this.tokens = tokens;
      this.index = 0;
    }

    peek() {
      return this.tokens[this.index] || null;
    }

    isWord(value) {
      const token = this.peek();
      return token?.type === 'word' && token.value.toUpperCase() === value;
    }

    isSymbol(value) {
      const token = this.peek();
      return token?.type === 'symbol' && token.value === value;
    }

    takeWord(value) {
      if (!this.isWord(value)) return false;
      this.index += 1;
      return true;
    }

    takeSymbol(value) {
      if (!this.isSymbol(value)) return false;
      this.index += 1;
      return true;
    }

    expectWord(value) {
      if (!this.takeWord(value)) throw new QueryParseError(`Expected ${value}.`);
    }

    expectSymbol(value) {
      if (!this.takeSymbol(value)) throw new QueryParseError(`Expected ${value}.`);
    }

    expectIdentifier() {
      const token = this.peek();
      if (token?.type !== 'identifier' || !token.value) throw new QueryParseError('Expected a quoted identifier.');
      this.index += 1;
      return token.value;
    }

    expectString() {
      const token = this.peek();
      if (token?.type !== 'string') throw new QueryParseError('Expected a quoted string.');
      this.index += 1;
      return token.value;
    }

    expectNumber() {
      const token = this.peek();
      if (token?.type !== 'number') throw new QueryParseError('Expected a number.');
      this.index += 1;
      const value = Number(token.value);
      if (!Number.isFinite(value)) throw new QueryParseError('Invalid number.');
      return {value, text: String(value)};
    }

    parseIdentifierList() {
      const identifiers = [this.expectIdentifier()];
      while (this.takeSymbol(',')) identifiers.push(this.expectIdentifier());
      if (new Set(identifiers).size !== identifiers.length) throw new QueryParseError('Duplicate selected field.');
      return identifiers;
    }

    parseBranchProjection() {
      const token = this.peek();
      if (!token) throw new QueryParseError('Missing branch projection.');

      if (token.type === 'identifier') {
        this.index += 1;
        return {alias: token.value, expression: 'column', value: token.value};
      }
      if (token.type === 'word' && token.value.toUpperCase() === 'NULL') {
        this.index += 1;
        this.expectWord('AS');
        return {alias: this.expectIdentifier(), expression: 'null', value: null};
      }
      if (token.type === 'string') {
        this.index += 1;
        this.expectWord('AS');
        return {alias: this.expectIdentifier(), expression: 'literal', value: token.value};
      }
      throw new QueryParseError('Unsupported branch projection.');
    }

    parseBranch() {
      this.expectWord('SELECT');
      const projection = [this.parseBranchProjection()];
      while (this.takeSymbol(',')) projection.push(this.parseBranchProjection());
      this.expectWord('FROM');
      const source = this.expectIdentifier();
      const match = /^selected_(data|voice|speech)$/.exec(source);
      if (!match) throw new QueryParseError('Unsupported CDR view.');
      return {kind: match[1], projection};
    }

    parseFilterAtom() {
      if (this.takeSymbol('(')) {
        const field = this.expectIdentifier();
        this.expectWord('IS');
        let operator;
        let connector;
        if (this.takeWord('NOT')) {
          this.expectWord('NULL');
          connector = 'AND';
          operator = 'not_empty';
          this.expectWord(connector);
        } else {
          this.expectWord('NULL');
          connector = 'OR';
          operator = 'empty';
          this.expectWord(connector);
        }
        if (this.expectIdentifier() !== field) throw new QueryParseError('Inconsistent empty filter.');
        this.expectSymbol(operator === 'empty' ? '=' : '<>');
        if (this.expectString() !== '') throw new QueryParseError('Invalid empty filter.');
        this.expectSymbol(')');
        return {field, operator, value: '', connector: 'AND'};
      }

      if (this.takeWord('INSTR')) {
        this.expectSymbol('(');
        this.expectWord('LOWER'); this.expectSymbol('(');
        this.expectWord('CAST'); this.expectSymbol('(');
        const field = this.expectIdentifier();
        this.expectWord('AS'); this.expectWord('TEXT');
        this.expectSymbol(')'); this.expectSymbol(')');
        this.expectSymbol(',');
        this.expectWord('LOWER'); this.expectSymbol('(');
        const value = this.expectString();
        this.expectSymbol(')'); this.expectSymbol(')');
        this.expectSymbol('>');
        if (this.expectNumber().value !== 0) throw new QueryParseError('Invalid contains filter.');
        if (!value.trim()) throw new QueryParseError('Empty filter value.');
        return {field, operator: 'contains', value, connector: 'AND'};
      }

      if (this.takeWord('SUBSTR')) {
        this.expectSymbol('(');
        this.expectWord('LOWER'); this.expectSymbol('(');
        this.expectWord('CAST'); this.expectSymbol('(');
        const field = this.expectIdentifier();
        this.expectWord('AS'); this.expectWord('TEXT');
        this.expectSymbol(')'); this.expectSymbol(')');
        this.expectSymbol(',');
        if (this.expectNumber().value !== 1) throw new QueryParseError('Invalid starts-with filter.');
        this.expectSymbol(',');
        this.expectWord('LENGTH'); this.expectSymbol('(');
        const lengthValue = this.expectString();
        this.expectSymbol(')'); this.expectSymbol(')');
        this.expectSymbol('=');
        this.expectWord('LOWER'); this.expectSymbol('(');
        const value = this.expectString();
        this.expectSymbol(')');
        if (lengthValue !== value || !value.trim()) throw new QueryParseError('Invalid starts-with filter.');
        return {field, operator: 'starts', value, connector: 'AND'};
      }

      if (this.takeWord('CAST')) {
        this.expectSymbol('(');
        const field = this.expectIdentifier();
        this.expectWord('AS'); this.expectWord('REAL');
        this.expectSymbol(')');
        const operatorToken = this.peek();
        if (operatorToken?.type !== 'symbol' || !['>', '<'].includes(operatorToken.value)) throw new QueryParseError('Unsupported numeric comparison.');
        this.index += 1;
        const value = this.expectNumber();
        return {field, operator: operatorToken.value === '>' ? 'gt' : 'lt', value: value.text, connector: 'AND'};
      }

      const field = this.expectIdentifier();
      const operatorToken = this.peek();
      if (operatorToken?.type !== 'symbol' || !['=', '<>'].includes(operatorToken.value)) throw new QueryParseError('Unsupported comparison.');
      this.index += 1;
      const value = this.expectString();
      this.expectWord('COLLATE'); this.expectWord('NOCASE');
      if (!value.trim()) throw new QueryParseError('Empty filter value.');
      return {field, operator: operatorToken.value === '=' ? 'eq' : 'ne', value, connector: 'AND'};
    }

    parseBooleanExpression() {
      if (this.isSymbol('(')) {
        const start = this.index;
        try {
          this.expectSymbol('(');
          const left = this.parseBooleanExpression();
          let connector;
          if (this.takeWord('AND')) connector = 'AND';
          else if (this.takeWord('OR')) connector = 'OR';
          else throw new QueryParseError('Expected a filter connector.');
          const right = this.parseFilterAtom();
          this.expectSymbol(')');
          right.connector = connector;
          return [...left, right];
        } catch (_error) {
          this.index = start;
        }
      }
      return [this.parseFilterAtom()];
    }

    parse() {
      this.expectWord('SELECT');
      const fields = this.parseIdentifierList();
      this.expectWord('FROM');
      this.expectSymbol('(');
      const branches = [this.parseBranch()];
      while (this.takeWord('UNION')) {
        this.expectWord('ALL');
        branches.push(this.parseBranch());
      }
      this.expectSymbol(')');
      this.expectWord('AS');
      if (this.expectIdentifier() !== 'combined_cdr') throw new QueryParseError('Unsupported combined-query alias.');

      const kinds = branches.map(branch => branch.kind);
      if (new Set(kinds).size !== kinds.length) throw new QueryParseError('Duplicate CDR type.');
      const firstProjection = branches[0].projection;
      const innerFields = firstProjection.slice(0, -1).map(item => item.alias);
      if (new Set(innerFields).size !== innerFields.length || innerFields.includes('cdr_type')) throw new QueryParseError('Invalid branch fields.');
      for (const branch of branches) {
        const typeProjection = branch.projection[branch.projection.length - 1];
        if (typeProjection?.alias !== 'cdr_type' || typeProjection.expression !== 'literal' || typeProjection.value !== branch.kind.toUpperCase()) {
          throw new QueryParseError('Invalid CDR type projection.');
        }
        const branchFields = branch.projection.slice(0, -1);
        if (branchFields.length !== innerFields.length || branchFields.some((item, index) => item.alias !== innerFields[index])) {
          throw new QueryParseError('Inconsistent branch projection.');
        }
        if (branchFields.some(item => item.expression === 'column' && item.value !== item.alias)
          || branchFields.some(item => item.expression === 'literal')) {
          throw new QueryParseError('Unsupported branch expression.');
        }
      }

      const filters = [];
      if (this.takeWord('WHERE')) filters.push(...this.parseBooleanExpression());

      let sortField = '';
      let sortDirection = 'ASC';
      if (this.takeWord('ORDER')) {
        this.expectWord('BY');
        sortField = this.expectIdentifier();
        if (this.takeWord('ASC')) sortDirection = 'ASC';
        else if (this.takeWord('DESC')) sortDirection = 'DESC';
        else throw new QueryParseError('Expected sort direction.');
      }

      let limit = null;
      if (this.takeWord('LIMIT')) {
        const parsedLimit = this.expectNumber().value;
        if (!Number.isInteger(parsedLimit) || parsedLimit < 1 || parsedLimit > 100000) throw new QueryParseError('Unsupported row limit.');
        limit = parsedLimit;
      }
      if (this.index !== this.tokens.length) throw new QueryParseError('Trailing SQL is unsupported.');

      const availableInnerFields = new Set([...innerFields, 'cdr_type']);
      if (fields.some(field => !availableInnerFields.has(field))) throw new QueryParseError('Selected field is not projected.');
      if (filters.some(filter => !availableInnerFields.has(filter.field))) throw new QueryParseError('Filter field is not projected.');
      if (sortField && !availableInnerFields.has(sortField)) throw new QueryParseError('Sort field is not projected.');

      const expectedInnerFields = [];
      for (const field of [...fields, ...filters.map(filter => filter.field), sortField]) {
        if (field && field !== 'cdr_type' && !expectedInnerFields.includes(field)) expectedInnerFields.push(field);
      }
      if (expectedInnerFields.length !== innerFields.length || expectedInnerFields.some((field, index) => field !== innerFields[index])) {
        throw new QueryParseError('Branch projection does not match the query controls.');
      }

      return {kinds, fields, filters, sortField, sortDirection, limit};
    }
  }

  const parseGeneratedSql = (sql) => {
    if (typeof sql !== 'string' || !sql.trim()) return null;
    try {
      return new GeneratedQueryParser(tokenize(sql)).parse();
    } catch (_error) {
      return null;
    }
  };

  globalThis.QueryBuilderAssistantState = Object.freeze({parseGeneratedSql});
})();
