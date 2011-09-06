class NotJpegFileError(Exception):
	pass

class MarkerNotRecognizedError(Exception):
	pass

class MarkerNotHandledError(Exception):
	pass

class Jpeg(object):
	# Please note the widespread use of self._index and self._buf throughout member functions here
	# self.__index will get modified across most calls
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

	def __init__(self, buf):
		self._index = 0
		self._buf = buf[:]
		self.image = None
		self.build_from_buf()

	def build_from_buf(self):
		marker = self.get_marker()
		if marker != 'SOI':
			raise NotJpegFileError
		self.handle_marker(marker) # for now we don't expect this will do anything on SOI
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
		return
	marker_handlers['SOI'] = handle_soi

	def handle_app0(self):
		return
	marker_handlers['APP0'] = handle_app0


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
