import struct
import math

class NotJpegFileError(Exception):
	pass

class MarkerNotRecognizedError(Exception):
	pass

class MarkerNotHandledError(Exception):
	pass

class BadFieldError(Exception):
	pass

class BadHuffmanTreeError(Exception):
	pass

class JpegHuffman(object):
	def __init__(self, cv_tuple):
		counts = cv_tuple[0]
		values = cv_tuple[1]

		self.build_lookups(counts, values)

	# build lookup dictionaries of code --> (symbol, length of symbol)
	#	this function assumes that codes are up to 2 bytes in length
	# in order to reduce the amount of checking required to retrieve
	#	a symbol, we just pass an entire byte into the high dict
	#	and then conditionally into the corresponding low dict if necessary
	def build_lookups(self, counts, values):
		MAX_CODE = 0xff

		counts_high = counts[:8]
		counts_low = counts[8:]

		self.high = {}
		high = self.high

		interval = 0x80
		code = 0
		length = 1
		# counts[0] <--> codes of length 1
		for count in counts_high:
			if (count * interval) + code > MAX_CODE:
				raise BadHuffmanTreeError(code, count, interval)
			for i in range(count):
				val = values.pop(0)
				for j in range(interval):
					high[code + j] = (val, length)
				code += interval
			interval >>= 1
			length += 1

		# short circuit - if we placed code MAX_CODE then we are done
		#	note that this implies code == MAX_CODE + 1
		if code == (MAX_CODE + 1):
			return

		print code

		# we didn't place all the codes in the high set, so now we need to do
		#	the remaining ones across 1 or more low sets
		lows = []
		for i in range(code, MAX_CODE + 1):
			low = {}
			high[i] = (low, -1) # we use length = -1 to indicate more checking required
			lows.append(low)

		interval = 0x80
		num_lows = len(lows)
		code = 0
		# and length = 9
		# now build all the lows
		# similar to above, but when we run out of space in one low, we hop to the next
		# note that no value can cross multiple lows and we pop a low off once it is full
		for count in counts_low:
			# this is the same validation as above but modified to allow multiple dicts
			# note that it evaluates the same if num_lows == 1
			if (count * interval) + code > (((MAX_CODE + 1) * num_lows) - 1):
				raise BadHuffmanTreeError(code, count, interval)
			for i in range(count):
				low = lows[0]
				val = values.pop(0)
				# it can be shown that this will never overflow a low
				# interval decreases monotonically and is always a power of 2
				#	as a result, it will always pack to the end of one low perfectly
				for j in range(interval):
					low[code + j] = (val, length)
				code += interval
				# now determine if we filled that low
				#	remove filled low and reset code to 0
				if code == (MAX_CODE + 1):
					lows.pop(0)
					code = 0
			interval >>= 1
			length += 1

		# XXX fill any remaining slots with bad code indicator ?

	def lookup(self, full_2bytes):
		high_byte = (full_2bytes >> 8) & 0xff
		high_val, high_len = self.high[high_byte]
		if high_len >= 0:
			return high_val, high_len

		low_byte = full_2bytes & 0xff
		return high_val[low_byte]

class Jpeg(object):
	# Please note the widespread use of self._index and self._buf throughout member functions here
	# self._index will get modified across most calls

	# various constants
	MAX_QUANTIZATION_TABLES = 4
	MAX_HUFFMAN_TABLES = 4

	# marker codes that identify the various headers in JPEG
	markers = {
			# The encoding process is actually stored as part of the SOF marker
			# For this reason, there are several SOF markers here
			'\xc0': 'SOF0',
			'\xc1': 'SOF1',
			'\xc2': 'SOF2',
			'\xc3': 'SOF3',

			# We take a break from SOF markers to bring you: DHT
			# 'DHT' = Define Huffman Tree
			'\xc4': 'DHT',

			# And now return to SOF markers
			'\xc5': 'SOF5',
			'\xc6': 'SOF6',
			'\xc7': 'SOF7',
			'\xc8': 'SOF_JPEG',
			'\xc9': 'SOF9',
			'\xca': 'SOF10',
			'\xcb': 'SOF11',

			# DAC marker
			'\xcc': 'DAC',

			# More SOF markers
			'\xcd': 'SOF13',
			'\xce': 'SOF14',
			'\xcf': 'SOF15',

			'\xd8': 'SOI',
			'\xd9': 'EOI',
			'\xda': 'SOS',
			'\xdb': 'DQT',

			'\xe0': 'APP0',
			'\xe1': 'APP1',
			'\xe2': 'APP2',
			'\xe3': 'APP3',
			'\xe4': 'APP4',
			'\xe5': 'APP5',
			'\xe6': 'APP6',
			'\xe7': 'APP7',
			'\xe8': 'APP8',
			'\xe9': 'APP9',
			'\xea': 'APP10',
			'\xeb': 'APP11',
			'\xec': 'APP12',
			'\xed': 'APP13',
			'\xee': 'APP14',
			'\xef': 'APP15',
	}

	marker_handlers = {}

	# zigzag order to standard (natural) array order lookup tables
	zigzag_natural = {
			2: [0, 1, 8, 9],
			3: [0, 1, 8, 16, 9, 2, 10, 17, 18],
			4: [0, 1, 8, 16, 9, 2, 3, 10,
				17, 24, 25, 18, 11, 19, 26, 27],
			5: [0, 1, 8, 16, 9, 2, 3, 10,
				17, 24, 32, 25, 18, 11, 4, 12,
				19, 26, 33, 34, 27, 20, 28, 35,
				36],
			6: [0, 1, 8, 16, 9, 2, 3, 10,
				17, 24, 32, 25, 18, 11, 4, 5,
				12, 19, 26, 33, 40, 41, 34, 27,
				20, 13, 21, 28, 35, 42, 43, 36,
				29, 37, 44, 45],
			7: [0, 1, 8, 16, 9, 2, 3, 10,
				17, 24, 32, 25, 18, 11, 4,  5,
				12, 19, 26, 33, 40, 48, 41, 34,
				27, 20, 13, 6, 14, 21, 28, 35,
				42, 49, 50, 43, 36, 29, 22, 30,
				37, 44, 51, 52, 45, 38, 46, 53,
				54],
			8: [0, 1, 8, 16, 9, 2, 3, 10,
				17, 24, 32, 25, 18, 11, 4, 5,
				12, 19, 26, 33, 40, 48, 41, 34,
				27, 20, 13, 6, 7, 14, 21, 28,
				35, 42, 49, 56, 57, 50, 43, 36,
				29, 22, 15, 23, 30, 37, 44, 51,
				58, 59, 52, 45, 38, 31, 39, 46,
				53, 60, 61, 54, 47, 55, 62, 63]
	}

	# DCT encoding types -- retrieve from SOF marker code
	# We use these as keys into self.encoding_type
	encoding_types = [
			'sequential',
			'progressive',
			'arithmetic_code',
			'lossless',
			'differential',
	]

	def __init__(self, buf):
		self._index = 0
		self._buf = buf[:]
		self.image = None

		# Use trackers to return back to parsed headers
		self.trackers = {}

		# Attributes gathered from APP0 header
		self.is_jfif = False
		self.jfif_version = (None, None)
		self.density_unit = None
		self.x_density = None
		self.y_density = None

		# Attributes gathered from DQT header
		self.quantization_tables = [[], [], [], []]
		self.quantization_high_precision = [False, False, False, False]

		# Attributes gathered from SOF header
		self.encoding_type = {}
		self.sample_precision = 0
		self.image_height = 0
		self.image_width = 0
		self.components = []

		# Attributes gathered from DHT header
		self.huffman_data = [None] * self.MAX_HUFFMAN_TABLES
		# each has dc, ac component
		for i in range(self.MAX_HUFFMAN_TABLES):
			self.huffman_data[i] = [None, None]

		# SOS
		self.huffman_ac = []
		self.huffman_dc = []

		self.build_from_buf()

	def build_from_buf(self):
		# First we expect to get a 'SOI' marker
		marker = self.get_marker()
		if marker != 'SOI':
			raise NotJpegFileError
		self.handle_marker(marker) # we don't expect this will do anything on SOI

		# XXX enforce that 'APP0' comes immediately after?

		# Now we are ready to handle markers in any arbitrary order
		while marker != 'EOI':
			marker = self.get_marker()
			self.handle_marker(marker)

	def get_marker(self):
		if self._buf[self._index] != '\xff':
			raise MarkerNotRecognizedError()
		marker = Jpeg.markers.get(self._buf[self._index + 1])
		if marker is None:
			raise MarkerNotRecognizedError(marker)
		self._index += 2
		return marker

	def handle_marker(self, marker):
		# XXX use instance method somehow instead of class?
		handler = Jpeg.marker_handlers.get(marker)
		if handler is None:
			raise MarkerNotHandledError(marker)
		tracker = self.trackers.get(marker, [])
		tracker.append(self._index)
		self.trackers[marker] = tracker
		return handler(self)

	# We define this next function for headers which we don't care about or can't do anything with
	#	but need to skip over anyway
	def handle_uninteresting_variable_length_header(self):
		index = self._index
		length = struct.unpack('>H', self._buf[index:index+2])[0]
		index += length
		self._index = index

	# Almost all the APP headers are headers we don't care about
	# We DO care about APP 0 though
	marker_handlers['APP1'] = handle_uninteresting_variable_length_header
	marker_handlers['APP2'] = handle_uninteresting_variable_length_header
	marker_handlers['APP3'] = handle_uninteresting_variable_length_header
	marker_handlers['APP4'] = handle_uninteresting_variable_length_header
	marker_handlers['APP5'] = handle_uninteresting_variable_length_header
	marker_handlers['APP6'] = handle_uninteresting_variable_length_header
	marker_handlers['APP7'] = handle_uninteresting_variable_length_header
	marker_handlers['APP8'] = handle_uninteresting_variable_length_header
	marker_handlers['APP9'] = handle_uninteresting_variable_length_header
	marker_handlers['APP10'] = handle_uninteresting_variable_length_header
	marker_handlers['APP11'] = handle_uninteresting_variable_length_header
	marker_handlers['APP12'] = handle_uninteresting_variable_length_header
	marker_handlers['APP13'] = handle_uninteresting_variable_length_header
	# We also care about APP14 in some cases
	marker_handlers['APP15'] = handle_uninteresting_variable_length_header

	def handle_soi(self):
		### no need to increase self._index here because soi is a 0-length header
		pass

	marker_handlers['SOI'] = handle_soi

	def handle_app0(self):
		# APP0 header which contains the 'JFIF' identifier, version, and potentially a thumbnail
		# This header can contain a thumbnail which we do not care about, just get the interesting fields
		INTERESTING_LEN = 14 # does not include 2-byte length field
		JFIF_IDENT = 'JFIF\x00'

		index = self._index

		# first get a 2-byte length field
		length = struct.unpack('>H', self._buf[index:index + 2])[0]

		index += 2
		interesting = length - 2

		if interesting > INTERESTING_LEN:
			interesting = INTERESTING_LEN
		elif interesting < INTERESTING_LEN:
			# XXX we could alternately handle the JFXX extension marker here instead
			raise BadFieldError('APP0')

		ident = self._buf[index:index+5]
		index += 5
		if ident != JFIF_IDENT:
			raise NotJpegFileError()
		self.is_jfif = True

		maj_version = struct.unpack('B', self._buf[index])[0]
		index += 1
		min_version = struct.unpack('B', self._buf[index])[0]
		index += 1
		self.jfif_version = (maj_version, min_version)
		
		
		density_unit = struct.unpack('B', self._buf[index])[0]
		index += 1
		x_density = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2
		y_density = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2
		self.density_unit = density_unit
		self.x_density = x_density
		self.y_density = y_density

		thumbnail_x_dim = struct.unpack('B', self._buf[index])[0]
		index += 1
		thumbnail_y_dim = struct.unpack('B', self._buf[index])[0]
		index += 1

		thumbnail_size = 3 * thumbnail_x_dim * thumbnail_y_dim # packed RGB values
		if length - (interesting + 2) != thumbnail_size:
			raise BadFieldError('APP0')
		index += thumbnail_size

		self._index = index

	marker_handlers['APP0'] = handle_app0


	def handle_dqt(self):
		# The DQT header contains one of the quantization tables used to encode the JPEG
		# These tables are needed to perform the IDCT
		# One header <--> one table (can have MAX_QUANTIZATION_TABLES)
		index = self._index

		length = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2

		# quantization table number is the bottom 4 bits, precision is a boolean from top 4 of
		# if we have precision marker, we use twice as many bytes for quant. table
		# note that the precision of the actual dct samples is stored in the sof header, not here
		quant_num_and_prec = struct.unpack('B', self._buf[index])[0]
		index += 1
		quant_num = quant_num_and_prec & 0x0f
		quant_precision = quant_num_and_prec >> 4
		if quant_num >= self.MAX_QUANTIZATION_TABLES:
			raise BadFieldError('DQT')

		# Get the number of entries present for the quant. table.
		# Subtract 3 to remove the previous fields' lengths and then div by 2 for higher precision table
		num_entries = length - 3
		if quant_precision:
			num_entries /= 2

		table = [1] * num_entries

		# We want to get the appropriate zigzag to natural conversion table
		# Note that if num_entries is not a square something is wrong
		# One dimension should be the sqrt of the number of entries
		# XXX Do we actually want to handle non-64-entry cases?
		dqt_dim = math.sqrt(num_entries)
		if int(dqt_dim) != dqt_dim:
			raise BadFieldError('DQT')
		zigzag_natural = self.zigzag_natural.get(dqt_dim)
		if zigzag_natural is None:
			raise BadFieldError('DQT')

		# for now we are going to make sure it's 8x8 only
		assert dqt_dim == 8

		# Now we simply move along, collecting bytes and filling table
		if quant_precision:
			# precompile struct just to move a bit quicker
			s = struct.Struct('>H')
			for i in range(num_entries):
				entry = s.unpack(self._buf[index:index+2])[0]
				table[zigzag_natural[i]] = entry
				index += 2
		else:
			s = struct.Struct('B')
			for i in range(num_entries):
				entry = s.unpack(self._buf[index:index+1])[0]
				table[zigzag_natural[i]] = entry
				index += 1

		self.quantization_tables[quant_num] = table
		self.quantization_high_precision[quant_num] = quant_precision
		self._index = index

	marker_handlers['DQT'] = handle_dqt

	# We define a single place to actually handle SOF headers
	#	The marker code for each kind of SOF defines its type, but the
	#	fields are the same across all kinds
	def handle_sof(self, **kwargs):
		# Allow the individual handlers to just specify which types are True
		#	Assume the rest are false
		for t in self.encoding_types:
			self.encoding_type[t] = kwargs.get(t, False)

		index = self._index

		length = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2

		self.sample_precision = struct.unpack('B', self._buf[index])[0]
		index += 1
		self.image_height = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2
		self.image_width = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2
		num_components = struct.unpack('B', self._buf[index])[0]
		index += 1

		if self.image_height == 0:
			raise BadFieldError()

		if self.image_width == 0:
			raise BadFieldError()

		if num_components == 0:
			raise BadFieldError()

		# 8 bytes removed from length to cover previous fields
		# 3 bytes retrieved per component
		if (length - 8) != (3 * num_components):
			raise BadFieldError()

		# XXX handle case where this header isn't present (not here)
		for i in range(num_components):
			component_id = struct.unpack('B', self._buf[index])[0]
			sample_factor = struct.unpack('B', self._buf[index + 1])[0]
			quant_tbl_index = struct.unpack('B', self._buf[index + 2])[0]
			index += 3
			h_sample_factor = (sample_factor >> 4) & 0x0f
			v_sample_factor = sample_factor & 0x0f
			if quant_tbl_index >= self.MAX_QUANTIZATION_TABLES:
				raise BadFieldError()
			d = {'id': component_id, 'h_factor': h_sample_factor, 'v_factor': v_sample_factor, 'quant_tbl_index': quant_tbl_index}
			self.components.append(d)

		self._index = index

	# And now we define the individual SOF types
	# SOF0 - Baseline DCT - no encoding types
	def handle_sof0(self):
		return self.handle_sof()
	marker_handlers['SOF0'] = handle_sof0

	# SOF1 - Sequential
	def handle_sof1(self):
		return self.handle_sof(sequential=True)
	marker_handlers['SOF1'] = handle_sof1

	# SOF2 - Progressive
	def handle_sof2(self):
		return self.handle_sof(progressive=True)
	marker_handlers['SOF2'] = handle_sof2

	# SOF3 - Lossless
	def handle_sof3(self):
		return self.handle_sof(lossless=True)
	marker_handlers['SOF3'] = handle_sof3

	# SOF4 - Doesn't exist!

	# SOF5 - Sequential / Differential coding
	def handle_sof5(self):
		return self.handle_sof(sequential=True, differential=True)
	marker_handlers['SOF5'] = handle_sof5

	# SOF6 - Progressive / Differential coding
	def handle_sof6(self):
		return self.handle_sof(progressive=True, differential=True)
	marker_handlers['SOF6'] = handle_sof6
	
	# SOF7 - Lossless / Differential coding
	def handle_sof7(self):
		return self.handle_sof(lossless=True, differential=True)
	marker_handlers['SOF7'] = handle_sof7

	# SOF8 (SOF 'JPEG') - ??? coding
	def handle_sof_jpeg(self):
		return self.handle_sof()
	#marker_handlers['SOF_JPEG'] = handle_sof_jpeg

	# SOF9 - Sequential / Arithmetic coding
	def handle_sof9(self):
		return self.handle_sof(sequential=True, arithmetic=True)
	marker_handlers['SOF9'] = handle_sof9

	# SOF10 - Progressive / Arithmetic coding
	def handle_sof10(self):
		return self.handle_sof(progressive=True, arithmetic=True)
	marker_handlers['SOF10'] = handle_sof10

	# SOF11 - Lossless / Arithmetic coding
	def handle_sof11(self):
		return self.handle_sof(progressive=True, differential=True)
	marker_handlers['SOF11'] = handle_sof11

	# SOF12 - Doesn't exist!

	# SOF13 - Sequential / Differential / Arithmetic coding
	def handle_sof13(self):
		return self.handle_sof(sequential=True, differential=True, arithmetic=True)
	marker_handlers['SOF13'] = handle_sof13

	# SOF14 - Progressive / Differential / Arithmetic coding
	def handle_sof14(self):
		return self.handle_sof(progressive=True, differential=True, arithmetic=True)
	marker_handlers['SOF14'] = handle_sof14

	# SOF15 - Lossless / Differential / Arithmetic coding
	def handle_sof15(self):
		return self.handle_sof(lossless=True, differential=True, arithmetic=True)
	marker_handlers['SOF15'] = handle_sof15

	# DHT - Define Huffman Tree
	# These huffman trees are used as the first step in getting the DCT components in the image data
	# We don't actually build the trees yet, that will come later in handle_sos
	def handle_dht(self):
		MAX_SYMBOL_LENGTH = 16 # bits
		MAX_NUM_SYMBOLS = 256

		index = self._index

		length = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2

		# We get one section of one component at a time
		# Every component has 2 huffman trees -- one for the DC, and one for the AC
		# There is no field telling us how many sections to expect, so we just march along until we run out
		#	In fact, 4 trees could be defined by 4 calls to handle_dht with 1 tree each, 1 call to handle_dht with 4 trees, etc
		# Also, we don't really check inside the loop if we violate the length but we will check after
		while index < self._index + length:
			huffman_index = struct.unpack('B', self._buf[index])[0]
			index += 1

			# next we grab the number of entries at each bit depth in this tree
			# e.g. 0,0,1,4 -> 1 symbol of length 2 bits, 4 symbols of length 3 bits, etc.
			# we also maintain a running total of how many symbols are in the tree
			total = 0
			counts = [0] * MAX_SYMBOL_LENGTH
			for i in range(MAX_SYMBOL_LENGTH):
				counts[i] = struct.unpack('B', self._buf[index])[0]
				index += 1
				total += counts[i]

			if total > MAX_NUM_SYMBOLS:
				raise BadFieldError()

			# next we retrieve the ordered huffman tree values
			# these values will fill the tree in row order, left to right
			values = [0] * total
			for i in range(total):
				values[i] = struct.unpack('B', self._buf[index])[0]
				index += 1

			# finally, we save this information to self.huffman_data
			# huffman_index has a bit flag in the high nibble to indicate dc or ac
			# we're going to take the flag off here
			# is_ac == !is_dc
			is_ac = bool(huffman_index & 0x10)
			huffman_index &= 0x0f

			if huffman_index > self.MAX_HUFFMAN_TABLES:
				raise BadFieldError()

			self.huffman_data[huffman_index][int(is_ac)] = (counts, values)

		if index != self._index + length:
			raise BadFieldError()

		self._index = index

	marker_handlers['DHT'] = handle_dht

	# here's where we actually build the RGB output pixels and validate consistency of headers
	def handle_sos(self):
		# now build the huffman objects
		for l in self.huffman_data:
			dc = l[0]
			ac = l[1]

			# XXX make sure the indices store correctly
			if dc is not None:
				self.huffman_dc.append(JpegHuffman(dc))
			if ac is not None:
				self.huffman_ac.append(JpegHuffman(ac))

		raise BadFieldError()

	marker_handlers['SOS'] = handle_sos

	# EOI indicates that we have reached the end of the image, so we're done
	def handle_eoi(self):
		pass

	marker_handlers['EOI'] = handle_eoi


class Foo(object):
	def __init__(self, _buf):
		next_b = False
		for b in _buf:
			if next_b:
				print hex(ord(b))
				next_b = False
			elif b == '\xff':
				next_b = True

def main():
	import sys
	argv = sys.argv
	filename = argv[1]
	f = open(filename)
	buf = f.read()
	f.close()
	Jpeg(buf)

if __name__ == '__main__':
	main()
