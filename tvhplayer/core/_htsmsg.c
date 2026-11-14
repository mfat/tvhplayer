/*
 * HTSMSG binary decoding in C, for tvhplayer.core.htsmsg.
 *
 * Decoding the tens of thousands of channel messages of a large playlist in
 * Python took seconds, and the thread doing it held the interpreter lock
 * the whole time, so the window could only run in the gaps. This decodes
 * exactly as htsmsg._decode_body does: same types, same replacement of
 * invalid UTF-8, same errors. htsmsg.py falls back to Python without it.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <limits.h>
#include <stdint.h>
#include <string.h>

enum {
    HMF_MAP = 1, HMF_S64 = 2, HMF_STR = 3, HMF_BIN = 4,
    HMF_LIST = 5, HMF_DBL = 6, HMF_BOOL = 7, HMF_UUID = 8,
};

/* htsmsg.Binary, set by htsmsg.py: binary fields are that bytes subclass. */
static PyObject *binary_type = NULL;

/*
 * Field names repeat in every message (channelName, services, ...). Reusing
 * one string object per name saves decoding it and, as a string keeps its
 * hash, hashing it again for every dictionary it goes into.
 */
#define NAME_SLOTS 512
#define NAME_MAX_LEN 48
static struct {
    Py_ssize_t len;
    char bytes[NAME_MAX_LEN];
    PyObject *name;
} names[NAME_SLOTS];

static PyObject *
field_name(const unsigned char *p, Py_ssize_t len)
{
    uint32_t h = 2166136261u;
    PyObject *name;
    if (len > NAME_MAX_LEN)
        return PyUnicode_DecodeUTF8((const char *)p, len, "replace");
    for (Py_ssize_t i = 0; i < len; i++)
        h = (h ^ p[i]) * 16777619u;
    h &= NAME_SLOTS - 1;
    if (names[h].name != NULL && names[h].len == len && memcmp(names[h].bytes, p, len) == 0) {
        Py_INCREF(names[h].name);
        return names[h].name;
    }
    name = PyUnicode_DecodeUTF8((const char *)p, len, "replace");
    if (name == NULL)
        return NULL;
    /* A colliding name replaces the slot's; the cache only saves work. */
    Py_XDECREF(names[h].name);
    Py_INCREF(name);
    names[h].name = name;
    names[h].len = len;
    memcpy(names[h].bytes, p, len);
    return name;
}

static PyObject *
decode_s64(const unsigned char *p, Py_ssize_t len)
{
    if (len == 0)
        return PyLong_FromLong(0);
    if (len > 8) {
        /* Not sent by Tvheadend; int.from_bytes(data, 'little') as in Python. */
        PyObject *data = PyBytes_FromStringAndSize((const char *)p, len);
        PyObject *result;
        if (data == NULL)
            return NULL;
        result = PyObject_CallMethod((PyObject *)&PyLong_Type, "from_bytes", "Os", data, "little");
        Py_DECREF(data);
        return result;
    }
    uint64_t value = 0;
    for (Py_ssize_t i = len - 1; i >= 0; i--)
        value = (value << 8) | p[i];
    if (len == 8 && value >= UINT64_C(0x8000000000000000))
        return PyLong_FromLongLong((long long)(value - UINT64_C(0x8000000000000000)) + LLONG_MIN);
    return PyLong_FromUnsignedLongLong(value);
}

static PyObject *
decode_double(const unsigned char *p, Py_ssize_t len)
{
    if (len != 8) {
        PyErr_SetString(PyExc_ValueError, "Invalid HTSMSG double");
        return NULL;
    }
#if PY_VERSION_HEX >= 0x030B0000
    return PyFloat_FromDouble(PyFloat_Unpack8((const char *)p, 1));
#else
    return PyFloat_FromDouble(_PyFloat_Unpack8(p, 1));
#endif
}

static PyObject *
decode_uuid(const unsigned char *p, Py_ssize_t len)
{
    static const char digits[] = "0123456789abcdef";
    PyObject *text = PyUnicode_New(len * 2, 127);
    Py_UCS1 *out;
    if (text == NULL)
        return NULL;
    out = PyUnicode_1BYTE_DATA(text);
    for (Py_ssize_t i = 0; i < len; i++) {
        out[2 * i] = digits[p[i] >> 4];
        out[2 * i + 1] = digits[p[i] & 15];
    }
    return text;
}

static PyObject *
decode_body(const unsigned char *body, Py_ssize_t offset, Py_ssize_t end, int is_list, int depth)
{
    PyObject *msg, *item, *name;

    if (depth > 200) {
        /* Python stops at its recursion limit; stop well before the C stack does. */
        PyErr_SetString(PyExc_RecursionError, "HTSMSG nested too deeply");
        return NULL;
    }
    msg = is_list ? PyList_New(0) : PyDict_New();
    if (msg == NULL)
        return NULL;
    while (offset + 6 <= end) {
        int type = body[offset];
        Py_ssize_t name_len = body[offset + 1];
        Py_ssize_t data_len = ((Py_ssize_t)body[offset + 2] << 24) | ((Py_ssize_t)body[offset + 3] << 16)
                              | ((Py_ssize_t)body[offset + 4] << 8) | (Py_ssize_t)body[offset + 5];
        Py_ssize_t start, stop;
        offset += 6;
        start = offset + name_len;
        stop = start + data_len;
        if (stop > end) {
            PyErr_SetString(PyExc_ValueError, "Truncated HTSMSG field");
            goto fail;
        }
        const unsigned char *data = body + start;
        switch (type) {
        case HMF_STR:
            item = PyUnicode_DecodeUTF8((const char *)data, data_len, "replace");
            break;
        case HMF_S64:
            item = decode_s64(data, data_len);
            break;
        case HMF_MAP:
        case HMF_LIST:
            item = decode_body(body, start, stop, type == HMF_LIST, depth + 1);
            break;
        case HMF_BIN: {
            PyObject *raw = PyBytes_FromStringAndSize((const char *)data, data_len);
            if (raw == NULL || binary_type == NULL) {
                item = raw;
            } else {
                item = PyObject_CallOneArg(binary_type, raw);
                Py_DECREF(raw);
            }
            break;
        }
        case HMF_BOOL:
            item = PyBool_FromLong(data_len > 0 && data[0] != 0);
            break;
        case HMF_DBL:
            item = decode_double(data, data_len);
            break;
        case HMF_UUID:
            item = decode_uuid(data, data_len);
            break;
        default:
            PyErr_Format(PyExc_ValueError, "Unknown HTSMSG type %d", type);
            goto fail;
        }
        if (item == NULL)
            goto fail;
        if (is_list) {
            if (PyList_Append(msg, item) < 0) {
                Py_DECREF(item);
                goto fail;
            }
        } else {
            name = field_name(body + offset, name_len);
            if (name == NULL || PyDict_SetItem(msg, name, item) < 0) {
                Py_XDECREF(name);
                Py_DECREF(item);
                goto fail;
            }
            Py_DECREF(name);
        }
        Py_DECREF(item);
        offset = stop;
    }
    if (offset != end) {
        PyErr_SetString(PyExc_ValueError, "Trailing bytes in HTSMSG body");
        goto fail;
    }
    return msg;
fail:
    Py_DECREF(msg);
    return NULL;
}

static PyObject *
deserialize(PyObject *self, PyObject *args)
{
    Py_buffer view;
    int is_list = 0;
    PyObject *result;
    if (!PyArg_ParseTuple(args, "y*|p", &view, &is_list))
        return NULL;
    result = decode_body((const unsigned char *)view.buf, 0, view.len, is_list, 0);
    PyBuffer_Release(&view);
    return result;
}

static PyObject *
set_binary_type(PyObject *self, PyObject *type)
{
    Py_XINCREF(type);
    Py_XSETREF(binary_type, type);
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"deserialize", deserialize, METH_VARARGS,
     "deserialize(body, is_list=False): decode an HTSMSG body without its length prefix."},
    {"set_binary_type", set_binary_type, METH_O,
     "set_binary_type(cls): the bytes subclass binary fields are returned as."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_htsmsg", "HTSMSG decoding in C.", -1, methods,
    NULL, NULL, NULL, NULL,
};

PyMODINIT_FUNC
PyInit__htsmsg(void)
{
    return PyModule_Create(&module);
}
