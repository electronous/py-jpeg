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

class Jpeg(object):
	# Please note the widespread use of self._index and self._buf throughout member functions here
	# self._index will get modified across most calls

	# various constants
	MAX_QUANTIZATION_TABLES = 4

	# marker codes that identify the various headers in JPEG
	markers = {
			'\xd8': 'SOI',
			'\xe0': 'APP0',
			'\xdb': 'DQT',
			'\xc0': 'SOF0',
			'\xc4': 'DHT',
			'\xda': 'SOS',
			'\xd9': 'EOI',
	}

	marker_handlers = {}

	# zigzag order to standard (natural) array order lookup tables
	zigzag_natural = {	2: [0, 1, 8, 9],
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
		return handler(self)

	def handle_soi(self):
		### no need to increase self._index here because soi is a 0-length header
		pass

	marker_handlers['SOI'] = handle_soi

	def handle_app0(self):
		# APP0 header which contains the 'JFIF' identifier, version, and potentially a thumbnail
		# This header can contain a thumbnail which we do not care about, just get the interesting fields
		INTERESTING_LEN = 14 # does not include 2-byte length field
		JFIF_IDENT = 'JFIF\x00'

		self.trackers['SOI'] = self._index
		index = self._index
		# first get a 2-byte length field
		length_slice = self._buf[index:index + 2]
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

		self._index = index

	marker_handlers['APP0'] = handle_app0

	def handle_dqt(self):
		# The DQT header contains one of the quantization tables used to encode the JPEG
		# These tables are needed to perform the IDCT
		# One header <--> one table (can have MAX_QUANTIZATION_TABLES)
		self.trackers['DQT'] = self._index
		index = self._index

		length = struct.unpack('>H', self._buf[index:index+2])[0]
		index += 2

		# quantization table number is the bottom 4 bits, precision is a boolean from top 4 of
		# if we have precision marker, we use twice as many bytes for quant. table
		quant_num_and_prec = struct.unpack('B', self._buf[index])[0]
		index += 1
		quant_num = quant_num_and_prec & 0x0f
		quant_precision = quant_num_and_prec >> 4
		if quant_num >= self.MAX_QUANTIZATION_TABLES:
			raise BadFieldError('DQT')

		table = self.quantization_tables[quant_num]

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

		self._index = index

	marker_handlers['DQT'] = handle_dqt


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
